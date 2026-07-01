from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.backup_scheduler import (
    DEFAULT_BACKUP_INTERVAL_SECONDS,
    BackupScheduler,
    backup_scheduler_config_from_env,
)
from app.database import init_db
from scripts.backup_crypto import BACKUP_ENCRYPTION_KEY_ENV, generate_backup_encryption_key


class BackupSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "openjson.sqlite3")
        init_db(self.db_path)
        os.environ.pop(BACKUP_ENCRYPTION_KEY_ENV, None)

    def tearDown(self) -> None:
        os.environ.pop(BACKUP_ENCRYPTION_KEY_ENV, None)
        self.tmp.cleanup()

    def test_config_defaults_to_disabled_daily_local_backups(self) -> None:
        config = backup_scheduler_config_from_env(db_path=self.db_path, env={})

        self.assertFalse(config.enabled)
        self.assertEqual(config.db_path, self.db_path)
        self.assertEqual(config.output_dir, str(Path(self.db_path).resolve().parent / "backups"))
        self.assertEqual(config.interval_seconds, DEFAULT_BACKUP_INTERVAL_SECONDS)
        self.assertEqual(config.retention_count, 7)
        self.assertFalse(config.encrypt)
        self.assertFalse(config.encryption_key_configured)

    def test_config_parses_render_backup_scheduler_env(self) -> None:
        config = backup_scheduler_config_from_env(
            db_path="/data/openjson.sqlite3",
            env={
                "OPENJSON_BACKUP_SCHEDULER_ENABLED": "1",
                "OPENJSON_BACKUP_OUTPUT_DIR": "/data/backups",
                "OPENJSON_BACKUP_INTERVAL_SECONDS": "86400",
                "OPENJSON_BACKUP_RETENTION_COUNT": "7",
                "OPENJSON_BACKUP_ENCRYPT": "1",
                BACKUP_ENCRYPTION_KEY_ENV: "configured-secret",
            },
        )

        self.assertTrue(config.enabled)
        self.assertEqual(config.output_dir, "/data/backups")
        self.assertEqual(config.interval_seconds, 86400)
        self.assertEqual(config.retention_count, 7)
        self.assertTrue(config.encrypt)
        self.assertTrue(config.encryption_key_configured)

    async def test_run_once_creates_encrypted_integrity_checked_backup(self) -> None:
        backup_dir = str(Path(self.tmp.name) / "scheduled-backups")
        encryption_key = generate_backup_encryption_key()
        os.environ[BACKUP_ENCRYPTION_KEY_ENV] = encryption_key
        config = backup_scheduler_config_from_env(
            db_path=self.db_path,
            env={
                "OPENJSON_BACKUP_OUTPUT_DIR": backup_dir,
                "OPENJSON_BACKUP_RETENTION_COUNT": "3",
                "OPENJSON_BACKUP_ENCRYPT": "1",
                BACKUP_ENCRYPTION_KEY_ENV: encryption_key,
            },
        )
        events: list[dict] = []
        scheduler = BackupScheduler(config, event_logger=events.append)

        result = await scheduler.run_once()

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["integrity"]["status"], "ok")
        self.assertTrue(result["backup_path"].endswith(".sqlite3.enc"))
        self.assertTrue(Path(result["backup_path"]).exists())
        self.assertTrue(Path(result["manifest_path"]).exists())
        self.assertEqual([event["status"] for event in events], ["started", "completed"])
        self.assertNotIn(encryption_key, str(events))


if __name__ == "__main__":
    unittest.main()
