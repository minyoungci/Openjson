from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.activity_service import get_project_activity
from app.database import connect, init_db
from app.document_service import create_document, patch_document
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class ProjectActivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.admin = create_user(self.db_path, email="admin@example.com", display_name="Admin")
        self.editor = create_user(self.db_path, email="editor@example.com", display_name="Editor")
        self.viewer = create_user(self.db_path, email="viewer@example.com", display_name="Viewer")
        self.nonmember = create_user(self.db_path, email="outside@example.com", display_name="Outside")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )
        self.other_project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Other Project",
        )
        for user, role in ((self.admin, "admin"), (self.editor, "editor"), (self.viewer, "viewer")):
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=user["id"],
                role=role,
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_document_activity(self) -> dict:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/model.json",
            content={"learning_rate": 0.001, "optimizer": {"name": "adam"}},
        )
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.editor["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
            reason="Tune learning rate",
        )
        return document

    def _counts(self) -> dict[str, int]:
        with connect(self.db_path) as conn:
            return {
                "document_events": conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"],
                "audit_log": conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"],
            }

    def _snapshot(self, document_id: str) -> object:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        return json.loads(row["current_snapshot_json"])

    def test_activity_merges_document_events_and_audit_log_without_mutation(self) -> None:
        document = self._create_document_activity()
        before_counts = self._counts()
        before_snapshot = self._snapshot(document["id"])

        result = get_project_activity(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(result["filters"], {"source": "all", "actor_id": None, "document_id": None})
        self.assertGreaterEqual(result["pagination"]["total"], 5)
        self.assertEqual({item["source"] for item in result["items"]}, {"document_event", "audit_log"})
        self.assertEqual(
            [item["created_at"] for item in result["items"]],
            sorted([item["created_at"] for item in result["items"]], reverse=True),
        )
        update_items = [
            item
            for item in result["items"]
            if item["source"] == "document_event" and item["activity_type"] == "document.update"
        ]
        self.assertEqual(len(update_items), 1)
        update = update_items[0]
        self.assertEqual(update["document_id"], document["id"])
        self.assertEqual(update["full_path"], "config/model.json")
        self.assertEqual(update["outcome"], "success")
        self.assertEqual(update["document_event"]["changed_paths"], ["/learning_rate"])
        self.assertEqual(update["document_event"]["reason"], "Tune learning rate")
        self.assertIsNone(update["audit_log"])
        self.assertNotIn("content", update)
        self.assertNotIn("patch", update["document_event"])
        audit_items = [item for item in result["items"] if item["activity_type"] == "project_member.add"]
        self.assertGreaterEqual(len(audit_items), 3)
        self.assertEqual(audit_items[0]["source"], "audit_log")
        self.assertEqual(audit_items[0]["outcome"], "success")
        self.assertEqual(audit_items[0]["audit_log"]["target_type"], "project_member")
        self.assertIsNone(audit_items[0]["document_event"])
        self.assertEqual(self._counts(), before_counts)
        self.assertEqual(self._snapshot(document["id"]), before_snapshot)

    def test_source_actor_document_filters_and_pagination(self) -> None:
        document = self._create_document_activity()

        document_events = get_project_activity(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            source="document_events",
        )
        audit_log = get_project_activity(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            source="audit_log",
        )
        editor_items = get_project_activity(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            activity_actor_id=self.editor["id"],
        )
        document_items = get_project_activity(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            document_id=document["id"],
        )
        first_page = get_project_activity(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            limit=1,
            offset=0,
        )

        self.assertEqual({item["source"] for item in document_events["items"]}, {"document_event"})
        self.assertEqual({item["source"] for item in audit_log["items"]}, {"audit_log"})
        self.assertEqual([item["activity_type"] for item in editor_items["items"]], ["document.update"])
        self.assertEqual({item["document_id"] for item in document_items["items"]}, {document["id"]})
        self.assertEqual(document_items["pagination"]["total"], 2)
        self.assertEqual(first_page["pagination"]["limit"], 1)
        self.assertEqual(first_page["pagination"]["offset"], 0)
        self.assertTrue(first_page["pagination"]["has_more"])
        self.assertEqual(len(first_page["items"]), 1)

    def test_validation_and_permission_policy(self) -> None:
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )
        invalid_cases = [
            {"source": "comments"},
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
            {"activity_actor_id": "   "},
            {"document_id": "   "},
        ]
        for kwargs in invalid_cases:
            with self.assertRaises(AppError) as raised:
                get_project_activity(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    **kwargs,
                )
            self.assertEqual(raised.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(AppError) as wrong_project:
            get_project_activity(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                document_id=other_document["id"],
            )
        self.assertEqual(wrong_project.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)
        self.assertEqual(wrong_project.exception.details["project_id"], self.project["id"])

        for actor_id in (self.owner["id"], self.admin["id"]):
            result = get_project_activity(
                self.db_path,
                project_id=self.project["id"],
                actor_id=actor_id,
            )
            self.assertGreaterEqual(result["pagination"]["total"], 3)

        for actor_id in (self.editor["id"], self.viewer["id"], self.nonmember["id"]):
            with self.assertRaises(AppError) as denied:
                get_project_activity(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=actor_id,
                )
            self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as missing_actor:
            get_project_activity(
                self.db_path,
                project_id=self.project["id"],
                actor_id=None,
            )
        self.assertEqual(missing_actor.exception.code, ErrorCode.AUTH_REQUIRED)

    def test_http_route_and_api_token_scope(self) -> None:
        document = self._create_document_activity()
        client = TestClient(create_app(self.db_path))
        owner_token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "owner activity token"},
        )
        viewer_token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.viewer["id"]},
            json={"name": "viewer activity token"},
        )
        self.assertEqual(owner_token_response.status_code, 200)
        self.assertEqual(viewer_token_response.status_code, 200)
        owner_token = owner_token_response.json()["token"]
        viewer_token = viewer_token_response.json()["token"]

        activity = client.get(
            f"/projects/{self.project['id']}/activity",
            headers={"Authorization": f"Bearer {owner_token}"},
            params={"source": "document_events", "actor_id": self.editor["id"]},
        )
        other_project_activity = client.get(
            f"/projects/{self.other_project['id']}/activity",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        viewer_denied = client.get(
            f"/projects/{self.project['id']}/activity",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )

        self.assertEqual(activity.status_code, 200)
        body = activity.json()
        self.assertEqual(body["pagination"]["total"], 1)
        self.assertEqual(body["items"][0]["document_id"], document["id"])
        self.assertEqual(body["items"][0]["activity_type"], "document.update")
        self.assertEqual(body["items"][0]["actor_id"], self.editor["id"])
        self.assertEqual(other_project_activity.status_code, 403)
        self.assertEqual(other_project_activity.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(viewer_denied.status_code, 403)
        self.assertEqual(viewer_denied.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

    def test_project_activity_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/activity", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
