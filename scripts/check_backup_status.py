from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backup_sqlite import BACKUP_FILE_PREFIX


DEFAULT_MAX_AGE_SECONDS = 25 * 60 * 60
MANIFEST_GLOB = f"{BACKUP_FILE_PREFIX}*.manifest.json"


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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    normalized = raw.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _check(status: bool, code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "ok" if status else "failed",
        "code": code,
        "message": message,
        "details": details or {},
    }


def _latest_manifest_path(output_dir: Path) -> Path | None:
    candidates = list(output_dir.glob(MANIFEST_GLOB))
    if not candidates:
        return None
    candidates.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    return candidates[0]


def check_latest_backup_status(
    output_dir: str,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    require_encrypted: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir).resolve()
    checked_at = now or _utc_now()
    report: dict[str, Any] = {
        "status": "failed",
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "output_dir": str(resolved_output_dir),
        "max_age_seconds": max_age_seconds,
        "require_encrypted": require_encrypted,
        "latest": None,
        "checks": {},
    }

    manifest_path = _latest_manifest_path(resolved_output_dir)
    if manifest_path is None:
        report["checks"]["manifest_found"] = _check(
            False,
            "BACKUP_MANIFEST_NOT_FOUND",
            "No OpenJson backup manifest was found.",
            {"manifest_glob": MANIFEST_GLOB},
        )
        return report

    report["checks"]["manifest_found"] = _check(
        True,
        "BACKUP_MANIFEST_FOUND",
        "Latest OpenJson backup manifest was found.",
        {"manifest_path": str(manifest_path)},
    )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report["checks"]["manifest_json"] = _check(
            False,
            "BACKUP_MANIFEST_JSON_INVALID",
            "Latest backup manifest is not valid JSON.",
            {"manifest_path": str(manifest_path), "line": exc.lineno, "column": exc.colno},
        )
        return report
    if not isinstance(manifest, dict):
        report["checks"]["manifest_json"] = _check(
            False,
            "BACKUP_MANIFEST_JSON_INVALID",
            "Latest backup manifest JSON must be an object.",
            {"manifest_path": str(manifest_path)},
        )
        return report
    report["checks"]["manifest_json"] = _check(
        True,
        "BACKUP_MANIFEST_JSON_VALID",
        "Latest backup manifest JSON is valid.",
        {"manifest_path": str(manifest_path)},
    )

    backup_path_raw = manifest.get("backup_path")
    backup_path = Path(backup_path_raw).resolve() if isinstance(backup_path_raw, str) and backup_path_raw else None
    backup_exists = bool(backup_path and backup_path.exists())
    report["checks"]["backup_file"] = _check(
        backup_exists,
        "BACKUP_FILE_FOUND" if backup_exists else "BACKUP_FILE_NOT_FOUND",
        "Backup file exists." if backup_exists else "Backup file referenced by manifest does not exist.",
        {"backup_path": str(backup_path) if backup_path else backup_path_raw},
    )

    created_at = _parse_utc_timestamp(manifest.get("created_at"))
    age_seconds = None
    if created_at is not None:
        age_seconds = max(0, int((checked_at - created_at).total_seconds()))
    report["checks"]["age"] = _check(
        created_at is not None and age_seconds is not None and age_seconds <= max_age_seconds,
        "BACKUP_AGE_OK" if created_at is not None and age_seconds is not None and age_seconds <= max_age_seconds else "BACKUP_TOO_OLD",
        "Backup age is within the configured maximum." if created_at is not None and age_seconds is not None and age_seconds <= max_age_seconds else "Backup age is missing, invalid, or too old.",
        {
            "created_at": manifest.get("created_at"),
            "age_seconds": age_seconds,
            "max_age_seconds": max_age_seconds,
        },
    )

    integrity = manifest.get("integrity") if isinstance(manifest.get("integrity"), dict) else {}
    integrity_status = integrity.get("status")
    report["checks"]["integrity"] = _check(
        integrity_status == "ok",
        "BACKUP_INTEGRITY_OK" if integrity_status == "ok" else "BACKUP_INTEGRITY_FAILED",
        "Backup manifest reports successful combined integrity." if integrity_status == "ok" else "Backup manifest does not report successful combined integrity.",
        {"integrity_status": integrity_status},
    )

    encryption = manifest.get("encryption") if isinstance(manifest.get("encryption"), dict) else {}
    encrypted = encryption.get("enabled") is True
    report["checks"]["encryption"] = _check(
        (not require_encrypted) or encrypted,
        "BACKUP_ENCRYPTION_OK" if (not require_encrypted) or encrypted else "BACKUP_ENCRYPTION_REQUIRED",
        "Backup encryption policy is satisfied." if (not require_encrypted) or encrypted else "Latest backup is not encrypted but encrypted backups are required.",
        {"encrypted": encrypted, "require_encrypted": require_encrypted},
    )

    size_matches = False
    sha_matches = False
    actual_size = None
    actual_sha256 = None
    if backup_exists and backup_path is not None:
        actual_size = backup_path.stat().st_size
        actual_sha256 = _sha256(backup_path)
        size_matches = actual_size == manifest.get("size_bytes")
        sha_matches = actual_sha256 == manifest.get("sha256")
    report["checks"]["size"] = _check(
        size_matches,
        "BACKUP_SIZE_OK" if size_matches else "BACKUP_SIZE_MISMATCH",
        "Backup size matches manifest." if size_matches else "Backup size does not match manifest.",
        {"expected": manifest.get("size_bytes"), "actual": actual_size},
    )
    report["checks"]["sha256"] = _check(
        sha_matches,
        "BACKUP_SHA256_OK" if sha_matches else "BACKUP_SHA256_MISMATCH",
        "Backup SHA-256 matches manifest." if sha_matches else "Backup SHA-256 does not match manifest.",
        {"expected": manifest.get("sha256"), "actual": actual_sha256},
    )

    report["latest"] = {
        "manifest_path": str(manifest_path),
        "backup_path": str(backup_path) if backup_path else backup_path_raw,
        "created_at": manifest.get("created_at"),
        "age_seconds": age_seconds,
        "size_bytes": manifest.get("size_bytes"),
        "sha256": manifest.get("sha256"),
        "integrity_status": integrity_status,
        "encrypted": encrypted,
    }
    report["status"] = "ok" if all(check["status"] == "ok" for check in report["checks"].values()) else "failed"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the latest OpenJson SQLite backup status.")
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("OPENJSON_BACKUP_OUTPUT_DIR"),
        help="Directory containing OpenJson backup files and manifests. Defaults to OPENJSON_BACKUP_OUTPUT_DIR.",
    )
    parser.add_argument(
        "--max-age-seconds",
        type=_positive_int,
        default=int(os.environ.get("OPENJSON_BACKUP_MAX_AGE_SECONDS") or DEFAULT_MAX_AGE_SECONDS),
        help="Maximum acceptable age for the latest backup. Defaults to 25 hours.",
    )
    parser.add_argument(
        "--require-encrypted",
        action="store_true",
        default=(os.environ.get("OPENJSON_BACKUP_ENCRYPT") or "").strip().lower() in {"1", "true", "yes", "on"},
        help="Require the latest backup manifest to report encryption.enabled=true.",
    )
    args = parser.parse_args()
    if not args.output_dir:
        parser.error("--output-dir is required unless OPENJSON_BACKUP_OUTPUT_DIR is set")

    report = check_latest_backup_status(
        args.output_dir,
        max_age_seconds=args.max_age_seconds,
        require_encrypted=args.require_encrypted,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
