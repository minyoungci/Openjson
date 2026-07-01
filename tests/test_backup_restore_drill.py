from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.database import connect, init_db
from app.document_service import create_document, patch_document
from app.workspace_service import create_project, create_user, create_workspace
from scripts.backup_crypto import generate_backup_encryption_key
from scripts.backup_restore_drill import run_backup_restore_drill


class BackupRestoreDrillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/drill.json",
            content={"value": 1},
        )
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("OPENJSON_BACKUP_ENCRYPTION_KEY", None)
        os.environ.pop("OPENJSON_BACKUP_ENCRYPTION_ENABLED", None)

    def test_backup_restore_drill_creates_backup_restores_and_removes_temp_db(self) -> None:
        backup_dir = str(Path(self.tmp.name) / "backups")

        result = run_backup_restore_drill(self.db_path, backup_dir, retention_count=3)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["backup"]["integrity"]["status"], "ok")
        self.assertEqual(result["restore"]["status"], "restored")
        self.assertEqual(result["restore"]["integrity"]["status"], "ok")
        self.assertTrue(Path(result["backup"]["backup_path"]).exists())
        self.assertTrue(Path(result["backup"]["manifest_path"]).exists())
        self.assertTrue(result["cleanup"]["restored_db_removed"])
        self.assertTrue(result["cleanup"]["temporary_restore_dir_removed"])
        self.assertFalse(Path(result["cleanup"]["restored_db_path"]).exists())

    def test_encrypted_backup_restore_drill_uses_key_and_keeps_requested_restore_db(self) -> None:
        backup_dir = str(Path(self.tmp.name) / "encrypted-backups")
        restore_dir = Path(self.tmp.name) / "restore-drill"
        encryption_key = generate_backup_encryption_key()

        result = run_backup_restore_drill(
            self.db_path,
            backup_dir,
            encrypt=True,
            encryption_key=encryption_key,
            restore_dir=str(restore_dir),
            keep_restored=True,
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["backup"]["backup_path"].endswith(".sqlite3.enc"))
        self.assertEqual(result["backup"]["encryption"]["enabled"], True)
        self.assertEqual(result["restore"]["decryption"]["status"], "ok")
        self.assertFalse(result["cleanup"]["restored_db_removed"])
        self.assertFalse(result["cleanup"]["temporary_restore_dir_removed"])
        self.assertTrue(Path(result["cleanup"]["restored_db_path"]).exists())

    def test_backup_restore_drill_skips_restore_when_backup_integrity_fails(self) -> None:
        backup_dir = str(Path(self.tmp.name) / "failed-backups")
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO schema_migrations (id, description, applied_at)
                VALUES (?, ?, ?)
                """,
                ("9999_unknown_drill", "Unexpected drill drift.", "2026-07-01T00:00:00Z"),
            )

        result = run_backup_restore_drill(self.db_path, backup_dir)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "backup_integrity_failed")
        self.assertEqual(result["backup"]["integrity"]["checks"]["migrations"]["status"], "failed")
        self.assertIsNone(result["restore"])
        self.assertEqual(result["cleanup"]["restored_db_path"], None)

    def test_backup_restore_drill_cli_writes_report(self) -> None:
        root = Path(__file__).resolve().parents[1]
        backup_dir = Path(self.tmp.name) / "cli-backups"
        report_path = Path(self.tmp.name) / "reports" / "drill.json"

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/backup_restore_drill.py",
                "--db-path",
                self.db_path,
                "--output-dir",
                str(backup_dir),
                "--report-path",
                str(report_path),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(completed.stdout)
        report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["backup"]["sha256"], payload["backup"]["sha256"])


if __name__ == "__main__":
    unittest.main()
