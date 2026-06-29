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


def _verify_backup_manifest(source: Path) -> dict[str, object]:
    manifest_path = source.with_suffix(".manifest.json")
    if not manifest_path.exists():
        return {
            "status": "not_found",
            "manifest_path": str(manifest_path),
            "message": "Adjacent backup manifest was not found.",
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "status": "failed",
            "manifest_path": str(manifest_path),
            "message": "Backup manifest is not valid JSON.",
            "details": {
                "field": "manifest",
                "message": exc.msg,
                "line": exc.lineno,
                "column": exc.colno,
                "position": exc.pos,
            },
        }
    expected_sha256 = manifest.get("sha256")
    expected_size = manifest.get("size_bytes")
    actual_sha256 = _sha256(source)
    actual_size = source.stat().st_size
    failures = []
    if expected_sha256 != actual_sha256:
        failures.append(
            {
                "field": "sha256",
                "expected": expected_sha256,
                "actual": actual_sha256,
            }
        )
    if expected_size != actual_size:
        failures.append(
            {
                "field": "size_bytes",
                "expected": expected_size,
                "actual": actual_size,
            }
        )
    if failures:
        return {
            "status": "failed",
            "manifest_path": str(manifest_path),
            "message": "Backup file does not match its manifest.",
            "failures": failures,
        }
    return {
        "status": "ok",
        "manifest_path": str(manifest_path),
        "sha256": actual_sha256,
        "size_bytes": actual_size,
    }


def restore_sqlite(backup_path: str, target_db_path: str, *, force: bool = False) -> dict[str, object]:
    source = Path(backup_path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Backup database does not exist: {source}")
    target = Path(target_db_path).resolve()
    if target.exists() and not force:
        raise FileExistsError(f"Target database already exists: {target}")
    manifest_verification = _verify_backup_manifest(source)
    if manifest_verification["status"] == "failed":
        return {
            "status": "failed",
            "backup_path": str(source),
            "target_db_path": str(target),
            "restored_at": None,
            "manifest_verification": manifest_verification,
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)

    integrity = check_database_integrity(str(target))
    return {
        "status": "restored",
        "backup_path": str(source),
        "target_db_path": str(target),
        "restored_at": utc_now(),
        "manifest_verification": manifest_verification,
        "integrity": integrity,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a SQLite backup for the OpenJson MVP database.")
    parser.add_argument("--backup-path", required=True, help="Backup SQLite database path.")
    parser.add_argument(
        "--target-db-path",
        default=os.environ.get("OPENJSON_DB_PATH", DEFAULT_DB_PATH),
        help="Restore target DB path. Defaults to OPENJSON_DB_PATH or ./openjson.sqlite3.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite the target database if it exists.")
    args = parser.parse_args()
    result = restore_sqlite(args.backup_path, args.target_db_path, force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "restored" or result["integrity"]["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
