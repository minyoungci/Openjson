from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import (
    create_document,
    delete_document,
    list_project_document_events,
    patch_document,
    restore_document,
    rollback_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class ProjectDocumentEventFeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
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
        for user, role in ((self.editor, "editor"), (self.viewer, "viewer")):
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=user["id"],
                role=role,
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]

    def _snapshot(self, document_id: str) -> object:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        return json.loads(row["current_snapshot_json"])

    def _create_model_events(self) -> tuple[dict, dict]:
        model = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/model.json",
            content={"learning_rate": 0.001, "optimizer": {"name": "adam"}, "items": [1, 2]},
        )
        patch_document(
            self.db_path,
            document_id=model["id"],
            actor_id=self.editor["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
            reason="Tune learning rate",
        )
        patch_document(
            self.db_path,
            document_id=model["id"],
            actor_id=self.owner["id"],
            base_version=2,
            patch=[{"op": "replace", "path": "/optimizer/name", "value": "sgd"}],
        )
        data = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="datasets/items.json",
            content={"items": [{"name": "first"}]},
        )
        patch_document(
            self.db_path,
            document_id=data["id"],
            actor_id=self.editor["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/items/0/name", "value": "second"}],
        )
        return model, data

    def test_feed_returns_project_events_newest_first_with_document_metadata_and_no_mutation(self) -> None:
        model, data = self._create_model_events()
        before_event_count = self._event_count()
        before_snapshot = self._snapshot(model["id"])

        result = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(result["pagination"], {"limit": 50, "offset": 0, "total": 5, "has_more": False})
        self.assertEqual(result["filters"], {"event_type": None, "actor_id": None, "document_id": None, "changed_path": None})
        self.assertEqual([event["result_version"] for event in result["events"]], [2, 1, 3, 2, 1])
        self.assertEqual([event["full_path"] for event in result["events"]], [
            "datasets/items.json",
            "datasets/items.json",
            "config/model.json",
            "config/model.json",
            "config/model.json",
        ])
        self.assertEqual({event["project_id"] for event in result["events"]}, {self.project["id"]})
        self.assertEqual({event["document_id"] for event in result["events"]}, {model["id"], data["id"]})
        self.assertIn("/items/0/name", result["events"][0]["changed_paths"])
        self.assertEqual(self._event_count(), before_event_count)
        self.assertEqual(self._snapshot(model["id"]), before_snapshot)

    def test_filters_cover_event_actor_document_root_and_changed_path(self) -> None:
        model, data = self._create_model_events()

        updates = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            event_type="update",
        )
        actor_events = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            event_actor_id=self.editor["id"],
        )
        document_events = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            document_id=model["id"],
        )
        root_events = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            changed_path="",
        )
        nested_events = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            changed_path="/optimizer/name",
        )
        array_events = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            changed_path="/items/0/name",
        )

        self.assertEqual([event["event_type"] for event in updates["events"]], ["update", "update", "update"])
        self.assertEqual([event["actor_id"] for event in actor_events["events"]], [self.editor["id"], self.editor["id"]])
        self.assertEqual({event["document_id"] for event in document_events["events"]}, {model["id"]})
        self.assertEqual([event["event_type"] for event in root_events["events"]], ["create", "create"])
        self.assertEqual([event["document_id"] for event in nested_events["events"]], [model["id"]])
        self.assertEqual(nested_events["events"][0]["after_values"][0]["value"], "sgd")
        self.assertEqual([event["document_id"] for event in array_events["events"]], [data["id"]])

        for bad_path in ("/optimizer~2name", "/optimizer~"):
            with self.assertRaises(AppError) as invalid_path:
                list_project_document_events(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    changed_path=bad_path,
                )
            self.assertEqual(invalid_path.exception.code, ErrorCode.INVALID_REQUEST)
            self.assertIn("JSON Pointer", invalid_path.exception.details["message"])
        self.assertEqual(self._event_count(), 5)
        self.assertEqual(self._snapshot(model["id"])["optimizer"]["name"], "sgd")

    def test_array_append_changed_path_filter_uses_concrete_path(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="datasets/appends.json",
            content={"items": [{"name": "first"}]},
        )
        patched = patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.editor["id"],
            base_version=1,
            patch=[{"op": "add", "path": "/items/-", "value": {"name": "second"}}],
        )

        concrete_path_events = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            changed_path="/items/1",
        )
        request_path_events = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            changed_path="/items/-",
        )

        self.assertEqual(patched["changed_paths"], ["/items/1"])
        self.assertEqual(concrete_path_events["pagination"]["total"], 1)
        self.assertEqual(concrete_path_events["events"][0]["document_id"], document["id"])
        self.assertEqual(concrete_path_events["events"][0]["changed_paths"], ["/items/1"])
        self.assertEqual(concrete_path_events["events"][0]["before_values"], [{"path": "/items/1", "exists": False, "value": None}])
        self.assertEqual(concrete_path_events["events"][0]["after_values"], [{"path": "/items/1", "exists": True, "value": {"name": "second"}}])
        self.assertEqual(request_path_events["pagination"]["total"], 0)

    def test_pagination_reports_total_and_has_more(self) -> None:
        self._create_model_events()

        first_page = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            limit=2,
            offset=0,
        )
        second_page = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            limit=2,
            offset=2,
        )

        self.assertEqual(first_page["pagination"], {"limit": 2, "offset": 0, "total": 5, "has_more": True})
        self.assertEqual(second_page["pagination"], {"limit": 2, "offset": 2, "total": 5, "has_more": True})
        self.assertEqual(len(first_page["events"]), 2)
        self.assertEqual(len(second_page["events"]), 2)
        self.assertNotEqual(first_page["events"][0]["id"], second_page["events"][0]["id"])

    def test_feed_includes_delete_restore_and_rollback_events(self) -> None:
        model, _data = self._create_model_events()
        rollback_document(
            self.db_path,
            document_id=model["id"],
            actor_id=self.owner["id"],
            base_version=3,
            target_version=1,
        )
        delete_document(
            self.db_path,
            document_id=model["id"],
            actor_id=self.owner["id"],
            base_version=4,
        )
        restore_document(
            self.db_path,
            document_id=model["id"],
            actor_id=self.owner["id"],
            base_version=5,
        )

        feed = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            document_id=model["id"],
        )

        self.assertEqual(
            [event["event_type"] for event in feed["events"]],
            ["restore", "delete", "rollback", "update", "update", "create"],
        )

    def test_validation_and_permissions(self) -> None:
        model, _data = self._create_model_events()
        invalid_cases = [
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
            {"event_type": "comment"},
            {"document_id": "   "},
            {"changed_path": "learning_rate"},
        ]
        for kwargs in invalid_cases:
            with self.assertRaises(AppError) as raised:
                list_project_document_events(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    **kwargs,
                )
            self.assertEqual(raised.exception.code, ErrorCode.INVALID_REQUEST)

        viewer_result = list_project_document_events(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
        )
        self.assertEqual(viewer_result["pagination"]["total"], 5)

        with self.assertRaises(AppError) as nonmember_error:
            list_project_document_events(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.nonmember["id"],
            )
        self.assertEqual(nonmember_error.exception.code, ErrorCode.PERMISSION_DENIED)

        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )
        with self.assertRaises(AppError) as wrong_project:
            list_project_document_events(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                document_id=other_document["id"],
            )
        self.assertEqual(wrong_project.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)
        self.assertEqual(wrong_project.exception.details["project_id"], self.project["id"])
        self.assertNotEqual(wrong_project.exception.details["document_id"], model["id"])

    def test_http_route_and_api_token_scope(self) -> None:
        model, _data = self._create_model_events()
        create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )
        before_invalid_count = self._event_count()
        before_invalid_snapshot = self._snapshot(model["id"])
        client = TestClient(create_app(self.db_path))
        token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "event feed token"},
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]

        listed = client.get(
            f"/projects/{self.project['id']}/document-events",
            headers={"Authorization": f"Bearer {token}"},
            params={"changed_path": "/learning_rate", "actor_id": self.editor["id"]},
        )
        other_list = client.get(
            f"/projects/{self.other_project['id']}/document-events",
            headers={"Authorization": f"Bearer {token}"},
        )
        invalid_paths = [
            client.get(
                f"/projects/{self.project['id']}/document-events",
                headers={"Authorization": f"Bearer {token}"},
                params={"changed_path": bad_path},
            )
            for bad_path in ("/optimizer~2name", "/optimizer~")
        ]

        self.assertEqual(listed.status_code, 200)
        body = listed.json()
        self.assertEqual(body["pagination"]["total"], 1)
        self.assertEqual(body["events"][0]["document_id"], model["id"])
        self.assertEqual(body["events"][0]["actor_id"], self.editor["id"])
        self.assertEqual(body["events"][0]["changed_paths"], ["/learning_rate"])
        self.assertEqual(other_list.status_code, 403)
        self.assertEqual(other_list.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        for response in invalid_paths:
            self.assertEqual(response.status_code, 400)
            error = response.json()["error"]
            self.assertEqual(error["code"], ErrorCode.INVALID_REQUEST)
            self.assertIn("JSON Pointer", error["details"]["message"])
        self.assertEqual(self._event_count(), before_invalid_count)
        self.assertEqual(self._snapshot(model["id"]), before_invalid_snapshot)

    def test_document_event_feed_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/document-events", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
