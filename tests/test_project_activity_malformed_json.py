from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.activity_service import get_project_activity
from app.database import connect, init_db
from app.document_service import create_document
from app.main import create_app
from app.workspace_service import create_project, create_user, create_workspace


class ProjectActivityMalformedJsonTests(unittest.TestCase):
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
        self.document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/activity-malformed.json",
            content={"value": 1},
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _counts(self) -> dict[str, int]:
        with connect(self.db_path) as conn:
            return {
                "document_events": conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"],
                "audit_log": conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"],
            }

    def _insert_malformed_changed_paths_event(self) -> str:
        event_id = "evt_activity_bad_changed_paths"
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
                    self.document["id"],
                    self.owner["id"],
                    json.dumps([{"op": "replace", "path": "/value", "value": 2}], separators=(",", ":")),
                    json.dumps([{"op": "replace", "path": "/value", "value": 1}], separators=(",", ":")),
                    '["/value"',
                    json.dumps([{"path": "/value", "exists": True, "value": 1}], separators=(",", ":")),
                    json.dumps([{"path": "/value", "exists": True, "value": 2}], separators=(",", ":")),
                    "Malformed activity changed paths",
                    "2026-06-28T00:00:01Z",
                ),
            )
            conn.execute(
                """
                UPDATE json_documents
                SET current_version = 2
                WHERE id = ?
                """,
                (self.document["id"],),
            )
        return event_id

    def test_activity_reports_malformed_document_event_changed_paths_json(self) -> None:
        event_id = self._insert_malformed_changed_paths_event()
        before_counts = self._counts()

        activity = get_project_activity(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            source="document_events",
        )
        item = next(row for row in activity["items"] if row["id"] == event_id)

        self.assertEqual(item["source"], "document_event")
        self.assertEqual(item["document_id"], self.document["id"])
        self.assertEqual(item["full_path"], "config/activity-malformed.json")
        self.assertIsNone(item["document_event"]["changed_paths"])
        self.assertEqual(item["document_event"]["json_errors"][0]["field"], "changed_paths")
        self.assertIn("message", item["document_event"]["json_errors"][0])
        self.assertEqual(self._counts(), before_counts)

    def test_http_activity_reports_malformed_document_event_changed_paths_json(self) -> None:
        event_id = self._insert_malformed_changed_paths_event()
        client = TestClient(create_app(self.db_path))

        response = client.get(
            f"/projects/{self.project['id']}/activity",
            headers={"X-Actor-Id": self.owner["id"]},
            params={"source": "document_events"},
        )

        self.assertEqual(response.status_code, 200)
        item = next(row for row in response.json()["items"] if row["id"] == event_id)
        self.assertIsNone(item["document_event"]["changed_paths"])
        self.assertEqual(item["document_event"]["json_errors"][0]["field"], "changed_paths")


if __name__ == "__main__":
    unittest.main()
