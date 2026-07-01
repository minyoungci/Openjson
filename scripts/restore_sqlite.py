from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import DEFAULT_DB_PATH, utc_now
from app.integrity_service import check_database_integrity
from scripts.backup_crypto import decrypt_backup_bytes, resolve_backup_encryption_key


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
        "manifest": manifest,
    }


def _decrypt_backup_to_tempfile(source: Path, manifest: dict[str, object], encryption_key: str | None) -> dict[str, object]:
    encryption = manifest.get("encryption")
    if not isinstance(encryption, dict) or not encryption.get("enabled"):
        return {
            "status": "not_encrypted",
            "source_path": str(source),
            "sqlite_path": str(source),
            "cleanup_path": None,
        }
    try:
        resolved_key = resolve_backup_encryption_key(encryption_key)
        plaintext = decrypt_backup_bytes(source.read_bytes(), resolved_key)
    except Exception as exc:
        return {
            "status": "failed",
            "message": str(exc),
            "cleanup_path": None,
        }

    expected_plaintext_size = encryption.get("plaintext_size_bytes")
    expected_plaintext_sha256 = encryption.get("plaintext_sha256")
    actual_plaintext_size = len(plaintext)
    actual_plaintext_sha256 = hashlib.sha256(plaintext).hexdigest()
    failures = []
    if expected_plaintext_size != actual_plaintext_size:
        failures.append(
            {
                "field": "plaintext_size_bytes",
                "expected": expected_plaintext_size,
                "actual": actual_plaintext_size,
            }
        )
    if expected_plaintext_sha256 != actual_plaintext_sha256:
        failures.append(
            {
                "field": "plaintext_sha256",
                "expected": expected_plaintext_sha256,
                "actual": actual_plaintext_sha256,
            }
        )
    if failures:
        return {
            "status": "failed",
            "message": "Decrypted backup does not match its manifest.",
            "failures": failures,
            "cleanup_path": None,
        }

    tmp = NamedTemporaryFile(prefix="openjson-restore-", suffix=".sqlite3", delete=False)
    try:
        tmp.write(plaintext)
        tmp.flush()
    finally:
        tmp.close()
    return {
        "status": "ok",
        "source_path": str(source),
        "sqlite_path": tmp.name,
        "cleanup_path": tmp.name,
        "algorithm": encryption.get("algorithm"),
        "plaintext_sha256": actual_plaintext_sha256,
        "plaintext_size_bytes": actual_plaintext_size,
    }


def restore_sqlite(
    backup_path: str,
    target_db_path: str,
    *,
    force: bool = False,
    encryption_key: str | None = None,
) -> dict[str, object]:
    source = Path(backup_path).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Backup database does not exist: {source}")
    target = Path(target_db_path).resolve()
    if target.exists() and not force:
        raise FileExistsError(f"Target database already exists: {target}")
    manifest_verification = _verify_backup_manifest(source)
    manifest = manifest_verification.pop("manifest", None)
    if manifest_verification["status"] == "failed":
        return {
            "status": "failed",
            "backup_path": str(source),
            "target_db_path": str(target),
            "restored_at": None,
            "manifest_verification": manifest_verification,
        }
    if source.suffix == ".enc" and manifest_verification["status"] == "not_found":
        return {
            "status": "failed",
            "backup_path": str(source),
            "target_db_path": str(target),
            "restored_at": None,
            "manifest_verification": manifest_verification,
            "decryption": {
                "status": "failed",
                "message": "Encrypted backups require an adjacent manifest before restore.",
            },
        }
    decryption = (
        _decrypt_backup_to_tempfile(source, manifest, encryption_key)
        if isinstance(manifest, dict)
        else {
            "status": "not_encrypted",
            "source_path": str(source),
            "sqlite_path": str(source),
            "cleanup_path": None,
        }
    )
    if decryption["status"] == "failed":
        return {
            "status": "failed",
            "backup_path": str(source),
            "target_db_path": str(target),
            "restored_at": None,
            "manifest_verification": manifest_verification,
            "decryption": decryption,
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    sqlite_source = Path(str(decryption["sqlite_path"]))
    try:
        with closing(sqlite3.connect(sqlite_source)) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    finally:
        cleanup_path = decryption.get("cleanup_path")
        if cleanup_path:
            Path(str(cleanup_path)).unlink(missing_ok=True)

    integrity = check_database_integrity(str(target))
    return {
        "status": "restored",
        "backup_path": str(source),
        "target_db_path": str(target),
        "restored_at": utc_now(),
        "manifest_verification": manifest_verification,
        "decryption": decryption,
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
    parser.add_argument(
        "--encryption-key",
        help="Backup encryption key. Prefer OPENJSON_BACKUP_ENCRYPTION_KEY to avoid shell history exposure.",
    )
    args = parser.parse_args()
    result = restore_sqlite(
        args.backup_path,
        args.target_db_path,
        force=args.force,
        encryption_key=args.encryption_key,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] != "restored" or result["integrity"]["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
