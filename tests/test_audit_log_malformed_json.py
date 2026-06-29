from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.activity_service import get_project_activity
from app.audit_service import list_project_audit_log
from app.database import connect, init_db
from app.export_service import export_project_archive
from app.main import create_app
from app.workspace_service import create_project, create_user, create_workspace


class AuditLogMalformedJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.viewer = create_user(self.db_path, email="viewer@example.com", display_name="Viewer")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _audit_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"]

    def _insert_malformed_audit_row(self) -> str:
        audit_id = "audit_bad_details"
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_log (
                    id,
                    actor_id,
                    workspace_id,
                    project_id,
                    document_id,
                    action,
                    target_type,
                    target_id,
                    outcome,
                    error_code,
                    details,
                    created_at
                )
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, 'failure', ?, ?, ?)
                """,
                (
                    audit_id,
                    self.owner["id"],
                    self.workspace["id"],
                    self.project["id"],
                    "project_member.add",
                    "project_member",
                    self.viewer["id"],
                    "INVALID_REQUEST",
                    '{"role":',
                    "2026-06-28T00:00:00Z",
                ),
            )
        return audit_id

    def test_audit_log_read_reports_malformed_details_json(self) -> None:
        audit_id = self._insert_malformed_audit_row()
        before_count = self._audit_count()

        result = list_project_audit_log(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )

        event = result["events"][0]
        self.assertEqual(event["id"], audit_id)
        self.assertIsNone(event["details"])
        self.assertEqual(event["details_error"]["field"], "details")
        self.assertIn("message", event["details_error"])
        self.assertEqual(self._audit_count(), before_count)

    def test_activity_and_export_report_malformed_audit_details_json(self) -> None:
        audit_id = self._insert_malformed_audit_row()

        activity = get_project_activity(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            source="audit_log",
        )
        activity_item = activity["items"][0]
        self.assertEqual(activity_item["id"], audit_id)
        self.assertIsNone(activity_item["audit_log"]["details"])
        self.assertEqual(activity_item["audit_log"]["details_error"]["field"], "details")

        archive = export_project_archive(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            include_audit_log=True,
        )
        exported_event = archive["audit_log"][0]
        self.assertEqual(exported_event["id"], audit_id)
        self.assertIsNone(exported_event["details"])
        self.assertEqual(exported_event["details_error"]["field"], "details")

    def test_http_audit_activity_and_export_surfaces_preserve_success_envelopes(self) -> None:
        audit_id = self._insert_malformed_audit_row()
        client = TestClient(create_app(self.db_path))
        headers = {"X-Actor-Id": self.owner["id"]}

        audit_response = client.get(f"/projects/{self.project['id']}/audit-log", headers=headers)
        activity_response = client.get(
            f"/projects/{self.project['id']}/activity",
            headers=headers,
            params={"source": "audit_log"},
        )
        export_response = client.get(
            f"/projects/{self.project['id']}/export",
            headers=headers,
            params={"include_audit_log": "true"},
        )

        self.assertEqual(audit_response.status_code, 200)
        self.assertEqual(audit_response.json()["events"][0]["id"], audit_id)
        self.assertIsNone(audit_response.json()["events"][0]["details"])
        self.assertEqual(audit_response.json()["events"][0]["details_error"]["field"], "details")

        self.assertEqual(activity_response.status_code, 200)
        self.assertEqual(activity_response.json()["items"][0]["id"], audit_id)
        self.assertIsNone(activity_response.json()["items"][0]["audit_log"]["details"])
        self.assertEqual(
            activity_response.json()["items"][0]["audit_log"]["details_error"]["field"],
            "details",
        )

        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response.json()["audit_log"][0]["id"], audit_id)
        self.assertIsNone(export_response.json()["audit_log"][0]["details"])
        self.assertEqual(export_response.json()["audit_log"][0]["details_error"]["field"], "details")


if __name__ == "__main__":
    unittest.main()
