from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import (
    create_document,
    get_document_path_blame,
    get_document_path_history,
    get_history,
    list_project_document_events,
)
from app.main import create_app
from app.workspace_service import create_project, create_user, create_workspace


class EventReadMalformedJsonTests(unittest.TestCase):
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

    def _create_document(self, full_path: str = "config/model.json") -> dict:
        return create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path=full_path,
            content={"value": 1},
        )

    def _insert_malformed_event(
        self,
        *,
        document_id: str,
        event_id: str,
        malformed_field: str,
    ) -> None:
        raw_fields = {
            "patch": json.dumps([{"op": "replace", "path": "/value", "value": 2}], separators=(",", ":")),
            "inverse_patch": json.dumps([{"op": "replace", "path": "/value", "value": 1}], separators=(",", ":")),
            "changed_paths": json.dumps(["/value"], separators=(",", ":")),
            "before_values": json.dumps([{"path": "/value", "exists": True, "value": 1}], separators=(",", ":")),
            "after_values": json.dumps([{"path": "/value", "exists": True, "value": 2}], separators=(",", ":")),
        }
        raw_fields[malformed_field] = '{"broken":'
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
                    raw_fields["patch"],
                    raw_fields["inverse_patch"],
                    raw_fields["changed_paths"],
                    raw_fields["before_values"],
                    raw_fields["after_values"],
                    f"Malformed read surface event {event_id}",
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

    def test_history_and_feed_return_malformed_event_json_diagnostics(self) -> None:
        document = self._create_document()
        self._insert_malformed_event(
            document_id=document["id"],
            event_id="evt_history_bad_patch",
            malformed_field="patch",
        )

        history = get_history(self.db_path, document["id"], actor_id=self.owner["id"])
        bad_history_event = history["events"][1]
        feed = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        bad_feed_event = next(event for event in feed["events"] if event["id"] == "evt_history_bad_patch")

        self.assertIsNone(bad_history_event["patch"])
        self.assertEqual(bad_history_event["changed_paths"], ["/value"])
        self.assertEqual(bad_history_event["json_errors"][0]["field"], "patch")
        self.assertEqual(bad_history_event["json_errors"][0]["message"], "Expecting value")
        self.assertIsNone(bad_feed_event["patch"])
        self.assertEqual(bad_feed_event["project_id"], self.project["id"])
        self.assertEqual(bad_feed_event["full_path"], "config/model.json")
        self.assertEqual(bad_feed_event["json_errors"][0]["field"], "patch")

    def test_feed_changed_path_filter_skips_malformed_changed_paths_without_error(self) -> None:
        document = self._create_document("config/malformed-changed-paths.json")
        self._insert_malformed_event(
            document_id=document["id"],
            event_id="evt_feed_bad_changed_paths",
            malformed_field="changed_paths",
        )
        client = TestClient(create_app(self.db_path))

        feed = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        filtered = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            changed_path="/value",
        )
        http_filtered = client.get(
            f"/projects/{self.project['id']}/document-events",
            headers={"X-Actor-Id": self.owner["id"]},
            params={"changed_path": "/value"},
        )

        bad_event = next(event for event in feed["events"] if event["id"] == "evt_feed_bad_changed_paths")
        self.assertIsNone(bad_event["changed_paths"])
        self.assertEqual(bad_event["json_errors"][0]["field"], "changed_paths")
        self.assertEqual(filtered["pagination"]["total"], 0)
        self.assertEqual(filtered["events"], [])
        self.assertEqual(http_filtered.status_code, 200)
        self.assertEqual(http_filtered.json()["pagination"]["total"], 0)

    def test_path_history_and_blame_report_replay_error_for_malformed_event_json(self) -> None:
        document = self._create_document("config/path-history-malformed.json")
        self._insert_malformed_event(
            document_id=document["id"],
            event_id="evt_path_bad_patch",
            malformed_field="patch",
        )
        client = TestClient(create_app(self.db_path))

        history = get_document_path_history(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            path="/value",
        )
        blame = get_document_path_blame(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            path="/value",
        )
        http_history = client.get(
            f"/documents/{document['id']}/path-history",
            headers={"X-Actor-Id": self.owner["id"]},
            params={"path": "/value"},
        )
        http_blame = client.get(
            f"/documents/{document['id']}/blame",
            headers={"X-Actor-Id": self.owner["id"]},
            params={"path": "/value"},
        )

        self.assertEqual([change["event_type"] for change in history["changes"]], ["create"])
        self.assertIsNone(history["latest"])
        self.assertIsNone(history["blame"])
        self.assertEqual(history["replay_error"]["code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(history["replay_error"]["details"]["event_id"], "evt_path_bad_patch")
        self.assertEqual(history["replay_error"]["details"]["failures"][0]["field"], "patch")
        self.assertIsNone(blame["latest"])
        self.assertIsNone(blame["blame"])
        self.assertEqual(blame["replay_error"], history["replay_error"])
        self.assertEqual(http_history.status_code, 200)
        self.assertEqual(http_history.json()["replay_error"]["details"]["event_id"], "evt_path_bad_patch")
        self.assertEqual(http_blame.status_code, 200)
        self.assertEqual(http_blame.json()["replay_error"]["details"]["event_id"], "evt_path_bad_patch")


if __name__ == "__main__":
    unittest.main()
