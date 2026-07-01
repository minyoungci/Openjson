from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import DEFAULT_DB_PATH, utc_now
from scripts.backup_sqlite import backup_sqlite
from scripts.restore_sqlite import restore_sqlite


def _positive_int(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if count < 1:
        raise argparse.ArgumentTypeError("must be greater than or equal to 1")
    return count


def run_backup_restore_drill(
    db_path: str,
    output_dir: str,
    *,
    retention_count: int | None = None,
    encrypt: bool = False,
    encryption_key: str | None = None,
    restore_dir: str | None = None,
    keep_restored: bool = False,
) -> dict[str, object]:
    started_at = utc_now()
    backup = backup_sqlite(
        db_path,
        output_dir,
        retention_count=retention_count,
        encrypt=encrypt,
        encryption_key=encryption_key,
    )
    result: dict[str, object] = {
        "status": "failed",
        "started_at": started_at,
        "completed_at": None,
        "backup": backup,
        "restore": None,
        "cleanup": {
            "restored_db_removed": False,
            "temporary_restore_dir_removed": False,
            "restored_db_path": None,
        },
    }
    if backup["integrity"]["status"] != "ok":
        result["completed_at"] = utc_now()
        result["failure_reason"] = "backup_integrity_failed"
        return result

    temporary_restore_dir: Path | None = None
    if restore_dir is None:
        temporary_restore_dir = Path(tempfile.mkdtemp(prefix="openjson-restore-drill-"))
        resolved_restore_dir = temporary_restore_dir
    else:
        resolved_restore_dir = Path(restore_dir).resolve()
        resolved_restore_dir.mkdir(parents=True, exist_ok=True)
    restored_db_path = resolved_restore_dir / f"openjson-restore-drill-{started_at.replace(':', '').replace('-', '')}.sqlite3"
    result["cleanup"]["restored_db_path"] = str(restored_db_path)

    try:
        restore = restore_sqlite(
            str(backup["backup_path"]),
            str(restored_db_path),
            encryption_key=encryption_key,
        )
        result["restore"] = restore
        if restore["status"] == "restored" and restore["integrity"]["status"] == "ok":
            result["status"] = "ok"
        else:
            result["failure_reason"] = "restore_integrity_failed"
    finally:
        if not keep_restored and restored_db_path.exists():
            restored_db_path.unlink()
            result["cleanup"]["restored_db_removed"] = True
        if temporary_restore_dir is not None and temporary_restore_dir.exists():
            shutil.rmtree(temporary_restore_dir)
            result["cleanup"]["temporary_restore_dir_removed"] = True
    result["completed_at"] = utc_now()
    return result


def _write_report(report_path: str, result: dict[str, object]) -> None:
    path = Path(report_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and restore a SQLite backup to verify disaster recovery.")
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
        help="Keep only this many latest backup files after a successful integrity-checked backup.",
    )
    parser.add_argument(
        "--encrypt",
        action="store_true",
        default=(os.environ.get("OPENJSON_BACKUP_ENCRYPTION_ENABLED") or "").strip().lower()
        in {"1", "true", "yes", "on"},
        help="Encrypt the backup file using OPENJSON_BACKUP_ENCRYPTION_KEY.",
    )
    parser.add_argument(
        "--encryption-key",
        help="Backup encryption key. Prefer OPENJSON_BACKUP_ENCRYPTION_KEY to avoid shell history exposure.",
    )
    parser.add_argument(
        "--restore-dir",
        help="Directory for the temporary restored DB. Defaults to an OS temporary directory.",
    )
    parser.add_argument(
        "--keep-restored",
        action="store_true",
        help="Keep the restored drill database for manual inspection.",
    )
    parser.add_argument("--report-path", help="Optional JSON report path.")
    args = parser.parse_args()

    result = run_backup_restore_drill(
        args.db_path,
        args.output_dir,
        retention_count=args.retention_count,
        encrypt=args.encrypt,
        encryption_key=args.encryption_key,
        restore_dir=args.restore_dir,
        keep_restored=args.keep_restored,
    )
    if args.report_path:
        _write_report(args.report_path, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
