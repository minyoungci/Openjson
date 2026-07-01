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


BACKUP_FILE_PREFIX = "openjson-backup-"
BACKUP_FILE_SUFFIX = ".sqlite3"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_int(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if count < 1:
        raise argparse.ArgumentTypeError("must be greater than or equal to 1")
    return count


def _backup_sort_key(path: Path) -> tuple[float, str]:
    return (path.stat().st_mtime, path.name)


def _prune_old_backups(
    *,
    output_dir: Path,
    keep_count: int,
    protected_paths: set[Path],
) -> dict[str, object]:
    if keep_count < 1:
        raise ValueError("keep_count must be greater than or equal to 1")

    protected_backup_count = 0
    candidates = []
    for candidate in output_dir.glob(f"{BACKUP_FILE_PREFIX}*{BACKUP_FILE_SUFFIX}"):
        resolved = candidate.resolve()
        if resolved in protected_paths:
            protected_backup_count += 1
            continue
        candidates.append(resolved)

    candidates.sort(key=_backup_sort_key)
    delete_count = max(0, len(candidates) - keep_count + protected_backup_count)
    to_delete = candidates[:delete_count]
    pruned: list[dict[str, object]] = []
    for backup_path in to_delete:
        manifest_path = backup_path.with_suffix(".manifest.json")
        removed_manifest = False
        backup_path.unlink()
        if manifest_path.exists():
            manifest_path.unlink()
            removed_manifest = True
        pruned.append(
            {
                "backup_path": str(backup_path),
                "manifest_path": str(manifest_path) if removed_manifest else None,
            }
        )

    remaining_count = len(list(output_dir.glob(f"{BACKUP_FILE_PREFIX}*{BACKUP_FILE_SUFFIX}")))
    return {
        "status": "ok",
        "keep_count": keep_count,
        "pruned_count": len(pruned),
        "remaining_count": remaining_count,
        "pruned": pruned,
    }


def backup_sqlite(db_path: str, output_dir: str, *, retention_count: int | None = None) -> dict[str, object]:
    source = Path(db_path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source database does not exist: {source}")
    if retention_count is not None and retention_count < 1:
        raise ValueError("retention_count must be greater than or equal to 1")
    destination_dir = Path(output_dir).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now().replace(":", "").replace("-", "").replace(".", "_")
    backup_path = destination_dir / f"{BACKUP_FILE_PREFIX}{timestamp}{BACKUP_FILE_SUFFIX}"

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

    if retention_count is None:
        manifest["retention"] = {"enabled": False}
    elif integrity["status"] != "ok":
        manifest["retention"] = {
            "enabled": True,
            "status": "skipped",
            "keep_count": retention_count,
            "reason": "integrity_failed",
        }
    else:
        manifest["retention"] = _prune_old_backups(
            output_dir=destination_dir,
            keep_count=retention_count,
            protected_paths={source, backup_path.resolve()},
        )

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
    retention_default = None
    retention_env = os.environ.get("OPENJSON_BACKUP_RETENTION_COUNT")
    if retention_env:
        try:
            retention_default = _positive_int(retention_env)
        except argparse.ArgumentTypeError as exc:
            parser.error(f"OPENJSON_BACKUP_RETENTION_COUNT {exc}")
    parser.add_argument(
        "--retention-count",
        type=_positive_int,
        default=retention_default,
        help=(
            "Keep only this many latest OpenJson SQLite backup files in the output directory "
            "after a successful integrity-checked backup. Defaults to OPENJSON_BACKUP_RETENTION_COUNT."
        ),
    )
    args = parser.parse_args()
    result = backup_sqlite(args.db_path, args.output_dir, retention_count=args.retention_count)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["integrity"]["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
