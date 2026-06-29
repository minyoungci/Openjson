from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import (
    assert_replay_matches_latest,
    create_document,
    diff_document_versions,
    get_document_version,
    rollback_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import create_project, create_user, create_workspace


class ReplayMalformedEventJsonTests(unittest.TestCase):
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
            full_path="config/replay.json",
            content={"value": 1},
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
                VALUES (?, ?, ?, NULL, 'update', 1, 2, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    event_id,
                    document_id,
                    self.owner["id"],
                    '{"broken":',
                    json.dumps([{"op": "replace", "path": "/value", "value": 1}], separators=(",", ":")),
                    json.dumps(["/value"], separators=(",", ":")),
                    json.dumps([{"path": "/value", "exists": True, "value": 1}], separators=(",", ":")),
                    json.dumps([{"path": "/value", "exists": True, "value": 2}], separators=(",", ":")),
                    f"Malformed replay event {event_id}",
                    "2026-06-28T00:00:01Z",
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

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _document_row(self, document_id: str) -> dict:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT current_version, current_snapshot_json
                FROM json_documents
                WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
        return {
            "current_version": row["current_version"],
            "content": json.loads(row["current_snapshot_json"]),
        }

    def test_version_and_diff_return_structured_errors_for_malformed_event_json(self) -> None:
        document = self._create_document()
        self._insert_malformed_patch_event(document_id=document["id"], event_id="evt_replay_bad_patch")
        client = TestClient(create_app(self.db_path))

        with self.assertRaises(AppError) as version_error:
            get_document_version(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                version=2,
            )
        with self.assertRaises(AppError) as diff_error:
            diff_document_versions(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                from_version=1,
                to_version=2,
            )
        http_version = client.get(
            f"/documents/{document['id']}/history/2",
            headers={"X-Actor-Id": self.owner["id"]},
        )
        http_diff = client.get(
            f"/documents/{document['id']}/diff",
            headers={"X-Actor-Id": self.owner["id"]},
            params={"from_version": 1, "to_version": 2},
        )

        for raised in (version_error.exception, diff_error.exception):
            self.assertEqual(raised.code, ErrorCode.INTERNAL_ERROR)
            self.assertEqual(raised.details["diagnostic_code"], "EVENT_JSON_DECODE_FAILED")
            self.assertEqual(raised.details["event_id"], "evt_replay_bad_patch")
            self.assertEqual(raised.details["failures"][0]["field"], "patch")
        self.assertEqual(http_version.status_code, 500)
        self.assertEqual(http_version.json()["error"]["code"], ErrorCode.INTERNAL_ERROR)
        self.assertEqual(http_version.json()["error"]["details"]["diagnostic_code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(http_diff.status_code, 500)
        self.assertEqual(http_diff.json()["error"]["details"]["event_id"], "evt_replay_bad_patch")

    def test_rollback_rejects_malformed_replay_input_without_partial_mutation(self) -> None:
        document = self._create_document()
        self._insert_malformed_patch_event(document_id=document["id"], event_id="evt_rollback_bad_patch")
        before_count = self._event_count(document["id"])
        before_row = self._document_row(document["id"])

        with self.assertRaises(AppError) as rollback_error:
            rollback_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                base_version=2,
                target_version=1,
            )
        with self.assertRaises(AppError) as replay_error:
            assert_replay_matches_latest(self.db_path, document["id"])

        self.assertEqual(rollback_error.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(rollback_error.exception.details["diagnostic_code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(rollback_error.exception.details["event_id"], "evt_rollback_bad_patch")
        self.assertEqual(replay_error.exception.details["event_id"], "evt_rollback_bad_patch")
        self.assertEqual(self._event_count(document["id"]), before_count)
        self.assertEqual(self._document_row(document["id"]), before_row)


if __name__ == "__main__":
    unittest.main()
