from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import init_db
from scripts.backup_crypto import generate_backup_encryption_key
from scripts.backup_sqlite import backup_sqlite
from scripts.check_backup_status import check_latest_backup_status


class BackupStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "openjson.sqlite3")
        init_db(self.db_path)

    def tearDown(self) -> None:
        os.environ.pop("OPENJSON_BACKUP_OUTPUT_DIR", None)
        os.environ.pop("OPENJSON_BACKUP_MAX_AGE_SECONDS", None)
        os.environ.pop("OPENJSON_BACKUP_ENCRYPT", None)
        self.tmp.cleanup()

    def test_latest_backup_status_passes_for_recent_integrity_checked_backup(self) -> None:
        backup_dir = str(Path(self.tmp.name) / "backups")
        manifest = backup_sqlite(self.db_path, backup_dir)

        report = check_latest_backup_status(backup_dir, max_age_seconds=90_000)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["latest"]["manifest_path"], manifest["manifest_path"])
        self.assertEqual(report["latest"]["backup_path"], manifest["backup_path"])
        self.assertEqual(report["checks"]["integrity"]["status"], "ok")
        self.assertEqual(report["checks"]["sha256"]["status"], "ok")
        self.assertEqual(report["checks"]["size"]["status"], "ok")
        self.assertFalse(report["latest"]["encrypted"])

    def test_latest_backup_status_requires_encryption_when_requested(self) -> None:
        backup_dir = str(Path(self.tmp.name) / "backups")
        backup_sqlite(self.db_path, backup_dir)

        report = check_latest_backup_status(
            backup_dir,
            max_age_seconds=90_000,
            require_encrypted=True,
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"]["encryption"]["code"], "BACKUP_ENCRYPTION_REQUIRED")

    def test_latest_backup_status_passes_for_encrypted_backup_without_exposing_key(self) -> None:
        backup_dir = str(Path(self.tmp.name) / "encrypted-backups")
        encryption_key = generate_backup_encryption_key()
        manifest = backup_sqlite(
            self.db_path,
            backup_dir,
            encrypt=True,
            encryption_key=encryption_key,
        )

        report = check_latest_backup_status(
            backup_dir,
            max_age_seconds=90_000,
            require_encrypted=True,
        )

        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["latest"]["encrypted"])
        self.assertEqual(report["latest"]["manifest_path"], manifest["manifest_path"])
        self.assertNotIn(encryption_key, json.dumps(report))

    def test_latest_backup_status_fails_when_backup_is_too_old(self) -> None:
        backup_dir = str(Path(self.tmp.name) / "old-backups")
        manifest = backup_sqlite(self.db_path, backup_dir)
        created_at = datetime.fromisoformat(str(manifest["created_at"]).replace("Z", "+00:00"))
        check_time = created_at + timedelta(seconds=91)

        report = check_latest_backup_status(
            backup_dir,
            max_age_seconds=90,
            now=check_time.astimezone(timezone.utc),
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"]["age"]["code"], "BACKUP_TOO_OLD")
        self.assertEqual(report["checks"]["age"]["details"]["age_seconds"], 91)

    def test_latest_backup_status_fails_when_manifest_or_backup_file_is_missing(self) -> None:
        missing_report = check_latest_backup_status(str(Path(self.tmp.name) / "missing"), max_age_seconds=90_000)
        self.assertEqual(missing_report["status"], "failed")
        self.assertEqual(missing_report["checks"]["manifest_found"]["code"], "BACKUP_MANIFEST_NOT_FOUND")

        backup_dir = str(Path(self.tmp.name) / "missing-file-backups")
        manifest = backup_sqlite(self.db_path, backup_dir)
        Path(str(manifest["backup_path"])).unlink()

        missing_file_report = check_latest_backup_status(backup_dir, max_age_seconds=90_000)

        self.assertEqual(missing_file_report["status"], "failed")
        self.assertEqual(missing_file_report["checks"]["backup_file"]["code"], "BACKUP_FILE_NOT_FOUND")
        self.assertEqual(missing_file_report["checks"]["sha256"]["code"], "BACKUP_SHA256_MISMATCH")

    def test_backup_status_cli_uses_environment_defaults_and_exit_codes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        backup_dir = Path(self.tmp.name) / "cli-backups"
        backup_sqlite(self.db_path, str(backup_dir))
        env = os.environ.copy()
        env["OPENJSON_BACKUP_OUTPUT_DIR"] = str(backup_dir)
        env["OPENJSON_BACKUP_MAX_AGE_SECONDS"] = "90000"
        env["OPENJSON_BACKUP_ENCRYPT"] = "0"

        ok = subprocess.run(
            [sys.executable, "scripts/check_backup_status.py"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(ok.stdout)

        self.assertEqual(payload["status"], "ok")

        failed = subprocess.run(
            [
                sys.executable,
                "scripts/check_backup_status.py",
                "--output-dir",
                str(Path(self.tmp.name) / "empty-backups"),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(failed.returncode, 1)
        self.assertEqual(json.loads(failed.stdout)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
