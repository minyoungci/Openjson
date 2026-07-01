from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.database import connect, init_db
from app.document_service import (
    assert_replay_matches_latest,
    create_document,
    delete_document,
    patch_document,
    reconstruct_document_at_version,
    restore_document,
    rollback_document,
)
from app.errors import AppError, ErrorCode
from app.snapshot_compaction_service import (
    compact_document_snapshot,
    compact_due_document_snapshots,
    list_document_snapshots,
    reconstruct_document_at_version_with_compaction,
)
from app.workspace_service import create_project, create_user, create_workspace


class DocumentSnapshotCompactionTests(unittest.TestCase):
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

    def _create_document(self) -> dict:
        return create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/model.json",
            content={"value": 0, "items": [1], "nested": {"enabled": True}},
        )

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _snapshot_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_snapshots WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _current_snapshot(self, document_id: str) -> object:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        return json.loads(row["current_snapshot_json"])

    def test_compacts_replayed_version_without_mutating_events_or_latest_snapshot(self) -> None:
        document = self._create_document()
        for base_version, value in [(1, 1), (2, 2), (3, 3), (4, 4)]:
            patch_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                base_version=base_version,
                patch=[{"op": "replace", "path": "/value", "value": value}],
            )
        before_event_count = self._event_count(document["id"])
        before_latest = self._current_snapshot(document["id"])

        snapshot = compact_document_snapshot(self.db_path, document_id=document["id"], version=3)
        reconstructed = reconstruct_document_at_version_with_compaction(
            self.db_path,
            document_id=document["id"],
            version=5,
        )

        self.assertTrue(snapshot["created"])
        self.assertEqual(snapshot["version"], 3)
        self.assertEqual(self._event_count(document["id"]), before_event_count)
        self.assertEqual(self._current_snapshot(document["id"]), before_latest)
        self.assertEqual(reconstructed["content"], reconstruct_document_at_version(self.db_path, document["id"], 5))
        self.assertTrue(reconstructed["used_compacted_snapshot"])
        self.assertEqual(reconstructed["compacted_snapshot"]["version"], 3)
        self.assertEqual(reconstructed["replayed_event_count"], 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_due_compaction_handles_rollback_delete_and_restore_sequences(self) -> None:
        document = self._create_document()
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/nested/enabled", "value": False}],
        )
        rollback_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=2,
            target_version=1,
        )
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

        result = compact_due_document_snapshots(
            self.db_path,
            document_id=document["id"],
            every_versions=2,
            include_latest=True,
        )
        reconstructed = reconstruct_document_at_version_with_compaction(
            self.db_path,
            document_id=document["id"],
            version=5,
        )
        listed = list_document_snapshots(self.db_path, document_id=document["id"])

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["snapshots_created"], 3)
        self.assertEqual([snapshot["version"] for snapshot in listed["snapshots"]], [2, 4, 5])
        self.assertEqual(reconstructed["content"], document["content"])
        self.assertTrue(reconstructed["used_compacted_snapshot"])
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_duplicate_compaction_is_idempotent_and_snapshot_rows_are_immutable(self) -> None:
        document = self._create_document()

        first = compact_document_snapshot(self.db_path, document_id=document["id"], version=1)
        second = compact_document_snapshot(self.db_path, document_id=document["id"], version=1)

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["id"], second["id"])
        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE document_snapshots SET snapshot_json = ? WHERE id = ?",
                    ('{"changed":true}', first["id"]),
                )
        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM document_snapshots WHERE id = ?", (first["id"],))

    def test_compaction_refuses_when_latest_snapshot_diverged_and_writes_nothing(self) -> None:
        document = self._create_document()
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 1}],
        )
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE json_documents SET current_snapshot_json = ? WHERE id = ?",
                ('{"value":999}', document["id"]),
            )

        with self.assertRaises(AppError) as error:
            compact_document_snapshot(self.db_path, document_id=document["id"], version=1)

        self.assertEqual(error.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(self._snapshot_count(document["id"]), 0)

    def test_compaction_cli_creates_latest_snapshot(self) -> None:
        document = self._create_document()
        root = Path(__file__).resolve().parents[1]

        completed = subprocess.run(
            [
                sys.executable,
                "scripts/compact_document_snapshots.py",
                "--db-path",
                self.db_path,
                "--document-id",
                document["id"],
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["snapshots_created"], 1)
        self.assertEqual(payload["snapshots"][0]["version"], 1)
        self.assertEqual(self._snapshot_count(document["id"]), 1)


if __name__ == "__main__":
    unittest.main()
