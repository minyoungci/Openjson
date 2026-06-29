from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import DEFAULT_DB_PATH, utc_now
from app.integrity_service import check_database_integrity


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_sqlite(db_path: str, output_dir: str) -> dict[str, object]:
    source = Path(db_path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source database does not exist: {source}")
    destination_dir = Path(output_dir).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now().replace(":", "").replace("-", "").replace(".", "_")
    backup_path = destination_dir / f"openjson-backup-{timestamp}.sqlite3"

    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(backup_path)) as dst:
        src.backup(dst)

    integrity = check_database_integrity(str(backup_path))
    manifest = {
        "status": "created",
        "source_db_path": str(source),
        "backup_path": str(backup_path),
        "size_bytes": backup_path.stat().st_size,
        "sha256": _sha256(backup_path),
        "created_at": utc_now(),
        "integrity": integrity,
    }
    manifest_path = backup_path.with_suffix(".manifest.json")
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a SQLite backup for the OpenJson MVP database.")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("OPENJSON_DB_PATH", DEFAULT_DB_PATH),
        help="SQLite DB path. Defaults to OPENJSON_DB_PATH or ./openjson.sqlite3.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where the backup and manifest should be written.",
    )
    args = parser.parse_args()
    result = backup_sqlite(args.db_path, args.output_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["integrity"]["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
