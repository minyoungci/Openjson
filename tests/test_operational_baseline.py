from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import create_document, delete_document, patch_document, restore_document, rollback_document
from app.integrity_service import check_database_integrity, check_event_chain_consistency, check_replay_consistency
from app.main import create_app
from app.workspace_service import create_project, create_user, create_workspace
from scripts.backup_sqlite import backup_sqlite
from scripts.restore_sqlite import restore_sqlite


class OperationalBaselineTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("OPENJSON_REQUEST_LOGGING", None)
        os.environ.pop("OPENJSON_CORS_ORIGINS", None)

    def _create_changed_document(self) -> dict:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/ops.json",
            content={"value": 1, "items": [1]},
        )
        patched = patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[
                {"op": "replace", "path": "/value", "value": 2},
                {"op": "add", "path": "/items/1", "value": 2},
            ],
        )
        rollback_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=patched["current_version"],
            target_version=1,
        )
        return document

    def _insert_event(
        self,
        *,
        document_id: str,
        event_id: str,
        event_type: str,
        base_version: int,
        result_version: int,
        patch: list[dict],
        inverse_patch: list[dict],
        changed_paths: list[str],
        before_values: list[dict],
        after_values: list[dict],
    ) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO document_events (
                    id,
                    document_id,
                    actor_id,
                    validation_schema_id,
                    event_type,
                    base_version,
                    result_version,
                    patch,
                    inverse_patch,
                    changed_paths,
                    before_values,
                    after_values,
                    summary,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    event_id,
                    document_id,
                    self.owner["id"],
                    event_type,
                    base_version,
                    result_version,
                    json.dumps(patch, separators=(",", ":")),
                    json.dumps(inverse_patch, separators=(",", ":")),
                    json.dumps(changed_paths, separators=(",", ":")),
                    json.dumps(before_values, separators=(",", ":")),
                    json.dumps(after_values, separators=(",", ":")),
                    f"Tampered event {event_id}",
                    "2026-06-28T00:00:00Z",
                ),
            )

    def _insert_malformed_patch_event(self, *, document_id: str, event_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO document_events (
                    id,
                    document_id,
                    actor_id,
                    validation_schema_id,
                    event_type,
                    base_version,
                    result_version,
                    patch,
                    inverse_patch,
                    changed_paths,
                    before_values,
                    after_values,
                    summary,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, NULL, 'update', 1, 2, ?, '[]', '[]', '[]', '[]', ?, NULL, ?)
                """,
                (
                    event_id,
                    document_id,
                    self.owner["id"],
                    '{"op":',
                    f"Malformed event {event_id}",
                    "2026-06-28T00:00:00Z",
                ),
            )
            conn.execute(
                """
                UPDATE json_documents
                SET current_version = 2
                WHERE id = ?
                """,
                (document_id,),
            )

    def _create_event_metadata_tampered_document(self, *, full_path: str, event_id: str) -> dict:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path=full_path,
            content={"value": 1},
        )
        self._insert_event(
            document_id=document["id"],
            event_id=event_id,
            event_type="update",
            base_version=1,
            result_version=2,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
            inverse_patch=[{"op": "replace", "path": "/value", "value": 1}],
            changed_paths=["/value"],
            before_values=[{"path": "/value", "exists": True, "value": 999}],
            after_values=[{"path": "/value", "exists": True, "value": 2}],
        )
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_version = 2,
                    current_snapshot_json = ?
                WHERE id = ?
                """,
                (json.dumps({"value": 2}, separators=(",", ":")), document["id"]),
            )
        return document

    def test_request_id_header_is_always_returned(self) -> None:
        client = TestClient(create_app(self.db_path))

        response = client.get("/health", headers={"X-Request-Id": "req_test_123"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-Id"], "req_test_123")

    def test_optional_structured_request_logging(self) -> None:
        os.environ["OPENJSON_REQUEST_LOGGING"] = "1"
        client = TestClient(create_app(self.db_path))
        output = io.StringIO()

        with redirect_stdout(output):
            response = client.get("/health", headers={"X-Request-Id": "req_logged"})

        self.assertEqual(response.status_code, 200)
        log_line = output.getvalue().strip()
        payload = json.loads(log_line)
        self.assertEqual(payload["event"], "http_request")
        self.assertEqual(payload["request_id"], "req_logged")
        self.assertEqual(payload["method"], "GET")
        self.assertEqual(payload["path"], "/health")
        self.assertEqual(payload["status_code"], 200)
        self.assertIn("duration_ms", payload)

    def test_replay_consistency_checker_passes_for_patch_rollback_delete_and_restore(self) -> None:
        document = self._create_changed_document()
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=3,
        )
        restore_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=4,
        )

        result = check_replay_consistency(self.db_path)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["checked_documents"], 1)
        self.assertEqual(result["failure_count"], 0)

    def test_replay_consistency_checker_detects_snapshot_tampering(self) -> None:
        document = self._create_changed_document()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_snapshot_json = ?
                WHERE id = ?
                """,
                (json.dumps({"tampered": True}, separators=(",", ":")), document["id"]),
            )

        result = check_replay_consistency(self.db_path)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["failures"][0]["document_id"], document["id"])
        self.assertEqual(result["failures"][0]["error_code"], "SNAPSHOT_REPLAY_MISMATCH")

    def test_replay_consistency_checker_reports_malformed_snapshot_json(self) -> None:
        document = self._create_changed_document()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_snapshot_json = ?
                WHERE id = ?
                """,
                ('{"broken":', document["id"]),
            )

        result = check_replay_consistency(self.db_path)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["failures"][0]["document_id"], document["id"])
        self.assertEqual(result["failures"][0]["error_code"], "SNAPSHOT_JSON_DECODE_FAILED")
        self.assertEqual(result["failures"][0]["details"]["field"], "current_snapshot_json")

    def test_event_chain_consistency_checker_reports_malformed_event_json(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/malformed-event.json",
            content={"value": 1},
        )
        self._insert_malformed_patch_event(document_id=document["id"], event_id="evt_malformed_json")

        result = check_event_chain_consistency(self.db_path)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["failures"][0]["document_id"], document["id"])
        self.assertEqual(result["failures"][0]["checks"]["event_metadata"], "failed")
        self.assertEqual(result["failures"][0]["failures"][0]["error_code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(result["failures"][0]["failures"][0]["event_id"], "evt_malformed_json")
        self.assertEqual(result["failures"][0]["failures"][0]["details"]["field"], "patch")

    def test_event_chain_consistency_checker_passes_for_patch_rollback_delete_and_restore(self) -> None:
        document = self._create_changed_document()
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=3,
        )
        restore_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=4,
        )

        result = check_event_chain_consistency(self.db_path)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["checked_documents"], 1)
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(result["failures"], [])

    def test_event_chain_consistency_checker_detects_metadata_tampering(self) -> None:
        document = self._create_event_metadata_tampered_document(
            full_path="config/event-chain.json",
            event_id="evt_bad_ops_metadata",
        )

        result = check_event_chain_consistency(self.db_path)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["failures"][0]["document_id"], document["id"])
        self.assertEqual(result["failures"][0]["checks"]["event_metadata"], "failed")
        self.assertEqual(result["failures"][0]["checks"]["replay_matches_latest"], "ok")
        error_codes = {failure["error_code"] for failure in result["failures"][0]["failures"]}
        self.assertIn("EVENT_BEFORE_VALUES_MISMATCH", error_codes)

    def test_replay_consistency_cli_returns_nonzero_on_failure(self) -> None:
        document = self._create_changed_document()
        root = Path(__file__).resolve().parents[1]

        success = subprocess.run(
            [sys.executable, "scripts/check_replay_consistency.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(success.returncode, 0)
        self.assertEqual(json.loads(success.stdout)["status"], "ok")

        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_version = ?
                WHERE id = ?
                """,
                (99, document["id"]),
            )
        failure = subprocess.run(
            [sys.executable, "scripts/check_replay_consistency.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(failure.returncode, 1)
        self.assertEqual(json.loads(failure.stdout)["status"], "failed")

    def test_event_chain_consistency_cli_returns_nonzero_on_failure(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/event-chain-cli.json",
            content={"value": 1},
        )
        root = Path(__file__).resolve().parents[1]

        success = subprocess.run(
            [sys.executable, "scripts/check_event_chain_integrity.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(success.returncode, 0)
        self.assertEqual(json.loads(success.stdout)["status"], "ok")

        self._insert_event(
            document_id=document["id"],
            event_id="evt_bad_ops_cli",
            event_type="update",
            base_version=1,
            result_version=2,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
            inverse_patch=[{"op": "replace", "path": "/value", "value": 1}],
            changed_paths=["/value"],
            before_values=[{"path": "/value", "exists": True, "value": 999}],
            after_values=[{"path": "/value", "exists": True, "value": 2}],
        )
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_version = 2,
                    current_snapshot_json = ?
                WHERE id = ?
                """,
                (json.dumps({"value": 2}, separators=(",", ":")), document["id"]),
            )
        failure = subprocess.run(
            [sys.executable, "scripts/check_event_chain_integrity.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(failure.returncode, 1)
        payload = json.loads(failure.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["failures"][0]["checks"]["event_metadata"], "failed")

    def test_database_integrity_cli_reports_malformed_event_json_without_crashing(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/database-integrity-malformed-event.json",
            content={"value": 1},
        )
        self._insert_malformed_patch_event(document_id=document["id"], event_id="evt_bad_json_cli")
        root = Path(__file__).resolve().parents[1]

        cli = subprocess.run(
            [sys.executable, "scripts/check_database_integrity.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(cli.returncode, 1)
        self.assertEqual(cli.stderr, "")
        payload = json.loads(cli.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["checks"]["replay"]["status"], "failed")
        self.assertEqual(payload["checks"]["event_chain"]["status"], "failed")
        replay_failure = payload["checks"]["replay"]["failures"][0]
        chain_failure = payload["checks"]["event_chain"]["failures"][0]["failures"][0]
        self.assertEqual(replay_failure["error_code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(replay_failure["details"]["failures"][0]["details"]["field"], "patch")
        self.assertEqual(chain_failure["error_code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(chain_failure["details"]["field"], "patch")

    def test_database_integrity_checker_and_cli_return_combined_status(self) -> None:
        self._create_changed_document()
        root = Path(__file__).resolve().parents[1]

        result = check_database_integrity(self.db_path)
        cli = subprocess.run(
            [sys.executable, "scripts/check_database_integrity.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["checks"]["replay"]["status"], "ok")
        self.assertEqual(result["checks"]["event_chain"]["status"], "ok")
        self.assertEqual(result["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(result["checks"]["sqlite"]["foreign_key_check"]["status"], "ok")
        self.assertEqual(result["checks"]["sqlite"]["integrity_check"]["status"], "ok")
        self.assertEqual(result["checks"]["migrations"]["status"], "ok")
        self.assertEqual(result["checks"]["migrations"]["ledger_status"], "ok")
        self.assertEqual(cli.returncode, 0)
        payload = json.loads(cli.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["checks"]["replay"]["status"], "ok")
        self.assertEqual(payload["checks"]["event_chain"]["status"], "ok")
        self.assertEqual(payload["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(payload["checks"]["migrations"]["status"], "ok")

    def test_database_integrity_checker_and_cli_fail_on_sqlite_foreign_key_failure(self) -> None:
        document = self._create_changed_document()
        root = Path(__file__).resolve().parents[1]
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                """
                UPDATE json_documents
                SET created_by = ?
                WHERE id = ?
                """,
                ("missing_user", document["id"]),
            )
            conn.commit()

        result = check_database_integrity(self.db_path)
        cli = subprocess.run(
            [sys.executable, "scripts/check_database_integrity.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["checks"]["replay"]["status"], "ok")
        self.assertEqual(result["checks"]["event_chain"]["status"], "ok")
        self.assertEqual(result["checks"]["sqlite"]["status"], "failed")
        self.assertEqual(result["checks"]["migrations"]["status"], "ok")
        self.assertEqual(result["checks"]["sqlite"]["foreign_key_check"]["status"], "failed")
        self.assertEqual(result["checks"]["sqlite"]["foreign_key_check"]["failure_count"], 1)
        self.assertEqual(result["checks"]["sqlite"]["foreign_key_check"]["failures"][0]["table"], "json_documents")
        self.assertEqual(cli.returncode, 1)
        payload = json.loads(cli.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["checks"]["sqlite"]["status"], "failed")
        self.assertEqual(payload["checks"]["sqlite"]["foreign_key_check"]["failures"][0]["parent"], "users")

    def test_database_integrity_checker_and_cli_fail_on_migration_ledger_drift(self) -> None:
        self._create_changed_document()
        root = Path(__file__).resolve().parents[1]
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO schema_migrations (id, description, applied_at)
                VALUES (?, ?, ?)
                """,
                ("9999_unknown_integrity_drift", "Unexpected migration drift.", "2026-06-28T00:00:00Z"),
            )

        result = check_database_integrity(self.db_path)
        cli = subprocess.run(
            [sys.executable, "scripts/check_database_integrity.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["checks"]["replay"]["status"], "ok")
        self.assertEqual(result["checks"]["event_chain"]["status"], "ok")
        self.assertEqual(result["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(result["checks"]["migrations"]["status"], "failed")
        self.assertEqual(result["checks"]["migrations"]["ledger_status"], "drift")
        self.assertEqual(result["checks"]["migrations"]["unknown_migrations"], ["9999_unknown_integrity_drift"])
        self.assertEqual(cli.returncode, 1)
        payload = json.loads(cli.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["checks"]["migrations"]["status"], "failed")
        self.assertEqual(payload["checks"]["migrations"]["unknown_migrations"], ["9999_unknown_integrity_drift"])

    def test_database_integrity_cli_fails_when_replay_fails(self) -> None:
        document = self._create_changed_document()
        root = Path(__file__).resolve().parents[1]
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_snapshot_json = ?
                WHERE id = ?
                """,
                (json.dumps({"tampered": True}, separators=(",", ":")), document["id"]),
            )

        cli = subprocess.run(
            [sys.executable, "scripts/check_database_integrity.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(cli.returncode, 1)
        payload = json.loads(cli.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["checks"]["replay"]["status"], "failed")
        self.assertEqual(payload["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(payload["checks"]["migrations"]["status"], "ok")

    def test_database_integrity_cli_fails_when_event_chain_metadata_fails(self) -> None:
        self._create_event_metadata_tampered_document(
            full_path="config/database-integrity-cli.json",
            event_id="evt_bad_database_integrity_cli",
        )
        root = Path(__file__).resolve().parents[1]

        cli = subprocess.run(
            [sys.executable, "scripts/check_database_integrity.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(cli.returncode, 1)
        payload = json.loads(cli.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["checks"]["replay"]["status"], "ok")
        self.assertEqual(payload["checks"]["event_chain"]["status"], "failed")
        self.assertEqual(payload["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(payload["checks"]["migrations"]["status"], "ok")

    def test_backup_and_restore_smoke_preserves_replay_consistency(self) -> None:
        self._create_changed_document()
        backup_dir = str(Path(self.tmp.name) / "backups")
        restored_db = str(Path(self.tmp.name) / "restored.sqlite3")
        source_bytes_before_backup = Path(self.db_path).read_bytes()

        backup_manifest = backup_sqlite(self.db_path, backup_dir)
        restore_result = restore_sqlite(backup_manifest["backup_path"], restored_db)

        self.assertEqual(backup_manifest["status"], "created")
        self.assertEqual(backup_manifest["integrity"]["status"], "ok")
        self.assertEqual(backup_manifest["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(backup_manifest["integrity"]["checks"]["event_chain"]["status"], "ok")
        self.assertEqual(backup_manifest["integrity"]["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(backup_manifest["integrity"]["checks"]["migrations"]["status"], "ok")
        self.assertTrue(Path(backup_manifest["backup_path"]).exists())
        self.assertTrue(Path(backup_manifest["manifest_path"]).exists())
        manifest_file_payload = json.loads(Path(backup_manifest["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest_file_payload["manifest_path"], backup_manifest["manifest_path"])
        self.assertEqual(manifest_file_payload["sha256"], backup_manifest["sha256"])
        self.assertEqual(Path(self.db_path).read_bytes(), source_bytes_before_backup)
        self.assertEqual(restore_result["status"], "restored")
        self.assertEqual(restore_result["manifest_verification"]["status"], "ok")
        self.assertEqual(restore_result["manifest_verification"]["sha256"], backup_manifest["sha256"])
        self.assertEqual(restore_result["manifest_verification"]["size_bytes"], backup_manifest["size_bytes"])
        self.assertEqual(restore_result["integrity"]["status"], "ok")
        self.assertEqual(restore_result["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(restore_result["integrity"]["checks"]["event_chain"]["status"], "ok")
        self.assertEqual(restore_result["integrity"]["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(restore_result["integrity"]["checks"]["migrations"]["status"], "ok")
        self.assertEqual(check_replay_consistency(restored_db)["status"], "ok")
        self.assertEqual(check_event_chain_consistency(restored_db)["status"], "ok")

    def test_backup_retention_prunes_oldest_successful_backup_pair(self) -> None:
        self._create_changed_document()
        backup_dir = str(Path(self.tmp.name) / "retention-backups")

        first = backup_sqlite(self.db_path, backup_dir, retention_count=5)
        time.sleep(0.01)
        second = backup_sqlite(self.db_path, backup_dir, retention_count=5)
        time.sleep(0.01)
        third = backup_sqlite(self.db_path, backup_dir, retention_count=2)

        self.assertEqual(third["integrity"]["status"], "ok")
        self.assertEqual(third["retention"]["status"], "ok")
        self.assertEqual(third["retention"]["keep_count"], 2)
        self.assertEqual(third["retention"]["pruned_count"], 1)
        self.assertEqual(third["retention"]["remaining_count"], 2)
        self.assertFalse(Path(first["backup_path"]).exists())
        self.assertFalse(Path(first["manifest_path"]).exists())
        self.assertTrue(Path(second["backup_path"]).exists())
        self.assertTrue(Path(second["manifest_path"]).exists())
        self.assertTrue(Path(third["backup_path"]).exists())
        self.assertTrue(Path(third["manifest_path"]).exists())
        self.assertEqual(
            len(list(Path(backup_dir).glob("openjson-backup-*.sqlite3"))),
            2,
        )

    def test_backup_retention_skips_pruning_when_integrity_fails(self) -> None:
        self._create_changed_document()
        backup_dir = str(Path(self.tmp.name) / "retention-failed-backups")
        first = backup_sqlite(self.db_path, backup_dir, retention_count=1)
        time.sleep(0.01)
        self._create_event_metadata_tampered_document(
            full_path="config/retention-failed-backup.json",
            event_id="evt_bad_retention_backup",
        )

        second = backup_sqlite(self.db_path, backup_dir, retention_count=1)

        self.assertEqual(second["integrity"]["status"], "failed")
        self.assertEqual(second["retention"]["status"], "skipped")
        self.assertEqual(second["retention"]["reason"], "integrity_failed")
        self.assertTrue(Path(first["backup_path"]).exists())
        self.assertTrue(Path(first["manifest_path"]).exists())
        self.assertTrue(Path(second["backup_path"]).exists())
        self.assertTrue(Path(second["manifest_path"]).exists())
        self.assertEqual(
            len(list(Path(backup_dir).glob("openjson-backup-*.sqlite3"))),
            2,
        )

    def test_restore_rejects_backup_that_does_not_match_manifest_before_copy(self) -> None:
        self._create_changed_document()
        backup_dir = str(Path(self.tmp.name) / "manifest-backups")
        restored_db = Path(self.tmp.name) / "manifest-restored.sqlite3"
        root = Path(__file__).resolve().parents[1]

        backup_manifest = backup_sqlite(self.db_path, backup_dir)
        with Path(backup_manifest["backup_path"]).open("ab") as handle:
            handle.write(b"tampered")

        restore_result = restore_sqlite(backup_manifest["backup_path"], str(restored_db))

        self.assertEqual(restore_result["status"], "failed")
        self.assertEqual(restore_result["manifest_verification"]["status"], "failed")
        self.assertEqual(restore_result["manifest_verification"]["message"], "Backup file does not match its manifest.")
        self.assertEqual(
            {failure["field"] for failure in restore_result["manifest_verification"]["failures"]},
            {"sha256", "size_bytes"},
        )
        self.assertFalse(restored_db.exists())

        restore_cli = subprocess.run(
            [
                sys.executable,
                "scripts/restore_sqlite.py",
                "--backup-path",
                backup_manifest["backup_path"],
                "--target-db-path",
                str(Path(self.tmp.name) / "manifest-restored-cli.sqlite3"),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(restore_cli.returncode, 1)
        restore_payload = json.loads(restore_cli.stdout)
        self.assertEqual(restore_payload["status"], "failed")
        self.assertEqual(restore_payload["manifest_verification"]["status"], "failed")
        self.assertFalse((Path(self.tmp.name) / "manifest-restored-cli.sqlite3").exists())

    def test_restore_rejects_malformed_manifest_json_before_copy(self) -> None:
        self._create_changed_document()
        backup_dir = str(Path(self.tmp.name) / "malformed-manifest-backups")
        restored_db = Path(self.tmp.name) / "malformed-manifest-restored.sqlite3"
        root = Path(__file__).resolve().parents[1]

        backup_manifest = backup_sqlite(self.db_path, backup_dir)
        Path(backup_manifest["manifest_path"]).write_text('{"sha256":', encoding="utf-8")

        restore_result = restore_sqlite(backup_manifest["backup_path"], str(restored_db))

        self.assertEqual(restore_result["status"], "failed")
        self.assertEqual(restore_result["manifest_verification"]["status"], "failed")
        self.assertEqual(restore_result["manifest_verification"]["message"], "Backup manifest is not valid JSON.")
        self.assertEqual(restore_result["manifest_verification"]["details"]["field"], "manifest")
        self.assertFalse(restored_db.exists())

        restore_cli = subprocess.run(
            [
                sys.executable,
                "scripts/restore_sqlite.py",
                "--backup-path",
                backup_manifest["backup_path"],
                "--target-db-path",
                str(Path(self.tmp.name) / "malformed-manifest-restored-cli.sqlite3"),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(restore_cli.returncode, 1)
        restore_payload = json.loads(restore_cli.stdout)
        self.assertEqual(restore_payload["status"], "failed")
        self.assertEqual(restore_payload["manifest_verification"]["status"], "failed")
        self.assertEqual(restore_payload["manifest_verification"]["details"]["field"], "manifest")
        self.assertFalse((Path(self.tmp.name) / "malformed-manifest-restored-cli.sqlite3").exists())

    def test_restore_with_missing_manifest_reports_not_found_and_runs_integrity(self) -> None:
        self._create_changed_document()
        backup_dir = str(Path(self.tmp.name) / "missing-manifest-backups")
        restored_db = Path(self.tmp.name) / "missing-manifest-restored.sqlite3"

        backup_manifest = backup_sqlite(self.db_path, backup_dir)
        Path(backup_manifest["manifest_path"]).unlink()

        restore_result = restore_sqlite(backup_manifest["backup_path"], str(restored_db))

        self.assertEqual(restore_result["status"], "restored")
        self.assertEqual(restore_result["manifest_verification"]["status"], "not_found")
        self.assertEqual(restore_result["integrity"]["status"], "ok")
        self.assertTrue(restored_db.exists())

    def test_backup_and_restore_fail_integrity_on_event_chain_metadata_corruption(self) -> None:
        self._create_event_metadata_tampered_document(
            full_path="config/event-chain-backup.json",
            event_id="evt_bad_ops_backup",
        )
        backup_dir = str(Path(self.tmp.name) / "tampered-backups")
        root = Path(__file__).resolve().parents[1]

        backup_manifest = backup_sqlite(self.db_path, backup_dir)

        self.assertEqual(backup_manifest["status"], "created")
        self.assertEqual(backup_manifest["integrity"]["status"], "failed")
        self.assertEqual(backup_manifest["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(backup_manifest["integrity"]["checks"]["event_chain"]["status"], "failed")
        self.assertEqual(backup_manifest["integrity"]["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(backup_manifest["integrity"]["checks"]["migrations"]["status"], "ok")

        backup_cli = subprocess.run(
            [
                sys.executable,
                "scripts/backup_sqlite.py",
                "--db-path",
                self.db_path,
                "--output-dir",
                str(Path(self.tmp.name) / "tampered-backups-cli"),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(backup_cli.returncode, 1)
        backup_payload = json.loads(backup_cli.stdout)
        self.assertEqual(backup_payload["integrity"]["status"], "failed")
        self.assertEqual(backup_payload["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(backup_payload["integrity"]["checks"]["event_chain"]["status"], "failed")
        self.assertEqual(backup_payload["integrity"]["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(backup_payload["integrity"]["checks"]["migrations"]["status"], "ok")

        restored_db = str(Path(self.tmp.name) / "tampered-restored.sqlite3")
        restore_result = restore_sqlite(backup_manifest["backup_path"], restored_db)
        self.assertEqual(restore_result["integrity"]["status"], "failed")
        self.assertEqual(restore_result["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(restore_result["integrity"]["checks"]["event_chain"]["status"], "failed")
        self.assertEqual(restore_result["integrity"]["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(restore_result["integrity"]["checks"]["migrations"]["status"], "ok")

        restore_cli = subprocess.run(
            [
                sys.executable,
                "scripts/restore_sqlite.py",
                "--backup-path",
                backup_manifest["backup_path"],
                "--target-db-path",
                str(Path(self.tmp.name) / "tampered-restored-cli.sqlite3"),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(restore_cli.returncode, 1)
        restore_payload = json.loads(restore_cli.stdout)
        self.assertEqual(restore_payload["integrity"]["status"], "failed")
        self.assertEqual(restore_payload["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(restore_payload["integrity"]["checks"]["event_chain"]["status"], "failed")
        self.assertEqual(restore_payload["integrity"]["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(restore_payload["integrity"]["checks"]["migrations"]["status"], "ok")

    def test_backup_and_restore_fail_integrity_on_migration_ledger_drift(self) -> None:
        self._create_changed_document()
        backup_dir = str(Path(self.tmp.name) / "migration-drift-backups")
        restored_db = str(Path(self.tmp.name) / "migration-drift-restored.sqlite3")
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO schema_migrations (id, description, applied_at)
                VALUES (?, ?, ?)
                """,
                ("9999_unknown_backup_drift", "Unexpected backup migration drift.", "2026-06-28T00:00:00Z"),
            )

        backup_manifest = backup_sqlite(self.db_path, backup_dir)
        restore_result = restore_sqlite(backup_manifest["backup_path"], restored_db)

        self.assertEqual(backup_manifest["status"], "created")
        self.assertEqual(backup_manifest["integrity"]["status"], "failed")
        self.assertEqual(backup_manifest["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(backup_manifest["integrity"]["checks"]["event_chain"]["status"], "ok")
        self.assertEqual(backup_manifest["integrity"]["checks"]["sqlite"]["status"], "ok")
        self.assertEqual(backup_manifest["integrity"]["checks"]["migrations"]["status"], "failed")
        self.assertEqual(
            backup_manifest["integrity"]["checks"]["migrations"]["unknown_migrations"],
            ["9999_unknown_backup_drift"],
        )
        self.assertEqual(restore_result["status"], "restored")
        self.assertEqual(restore_result["integrity"]["status"], "failed")
        self.assertEqual(restore_result["integrity"]["checks"]["migrations"]["status"], "failed")
        self.assertEqual(
            restore_result["integrity"]["checks"]["migrations"]["unknown_migrations"],
            ["9999_unknown_backup_drift"],
        )

    def test_restore_refuses_to_overwrite_without_force(self) -> None:
        self._create_changed_document()
        backup_dir = str(Path(self.tmp.name) / "backups")
        restored_db = str(Path(self.tmp.name) / "restored.sqlite3")
        backup_manifest = backup_sqlite(self.db_path, backup_dir)
        restore_sqlite(backup_manifest["backup_path"], restored_db)

        with self.assertRaises(FileExistsError):
            restore_sqlite(backup_manifest["backup_path"], restored_db)

        forced = restore_sqlite(backup_manifest["backup_path"], restored_db, force=True)
        self.assertEqual(forced["integrity"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
