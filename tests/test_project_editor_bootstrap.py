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
    delete_document,
    get_project_editor_bootstrap,
    patch_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class ProjectEditorBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.viewer = create_user(self.db_path, email="viewer@example.com", display_name="Viewer")
        self.nonmember = create_user(self.db_path, email="outside@example.com", display_name="Outside")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
            description="Editor bootstrap project",
        )
        self.other_project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Other Project",
        )
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
            role="viewer",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_document(self, full_path: str, content: object | None = None) -> dict:
        return create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path=full_path,
            content=content if content is not None else {"path": full_path},
        )

    def _event_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]

    def _document_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"]

    def _snapshot(self, document_id: str) -> object:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        return json.loads(row["current_snapshot_json"])

    def test_bootstrap_returns_project_list_tree_and_selected_editor_state_without_mutation(self) -> None:
        self._create_document("README.json")
        model = self._create_document("config/model.json", {"kind": "model", "value": 1})
        self._create_document("config/train/params.json")
        self._create_document("datasets/raw/items.json")
        patched = patch_document(
            self.db_path,
            document_id=model["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
            reason="prepare bootstrap selected editor state",
        )
        before_events = self._event_count()
        before_snapshot = self._snapshot(model["id"])

        result = get_project_editor_bootstrap(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            selected_document_id=model["id"],
            include_validation=True,
            recent_events_limit=1,
            path_prefix="config/",
            q="MODEL",
            limit=10,
            offset=0,
        )

        self.assertEqual(result["project"]["id"], self.project["id"])
        self.assertEqual(result["project"]["role"], "owner")
        self.assertEqual(result["actor"]["id"], self.owner["id"])
        self.assertEqual(result["actor"]["role"], "owner")
        self.assertTrue(result["actor"]["capabilities"]["can_patch"])
        self.assertEqual(result["bootstrap"]["mode"], "project_editor_bootstrap")
        self.assertEqual(result["bootstrap"]["version"], "task095.project_editor_bootstrap.v1")
        self.assertTrue(result["bootstrap"]["read_only"])
        self.assertEqual(result["bootstrap"]["selected_document_id"], model["id"])
        self.assertTrue(result["bootstrap"]["include_selected_document"])
        self.assertFalse(result["bootstrap"]["event_creation"]["creates_document_event"])
        self.assertTrue(result["bootstrap"]["actions"]["open_document"]["read_only"])
        self.assertEqual(
            [document["full_path"] for document in result["documents"]["documents"]],
            ["config/model.json"],
        )
        self.assertEqual(result["documents"]["pagination"], {"limit": 10, "offset": 0, "total": 1, "has_more": False})
        self.assertEqual(result["documents"]["filters"], {"include_deleted": False, "path_prefix": "config", "q": "MODEL"})
        self.assertNotIn("content", result["documents"]["documents"][0])
        self.assertEqual(result["document_tree"]["root"]["path"], "config")
        self.assertEqual(result["document_tree"]["summary"], {"document_count": 2, "folder_count": 1, "deleted_document_count": 0})
        self.assertEqual([child["name"] for child in result["document_tree"]["root"]["children"]], ["train", "model.json"])
        selected = result["selected_document_editor_state"]
        self.assertEqual(selected["document"]["id"], model["id"])
        self.assertEqual(selected["document"]["content"], {"kind": "model", "value": 2})
        self.assertEqual(json.loads(selected["document"]["content_text"]), selected["document"]["content"])
        self.assertEqual(selected["editor"]["required_base_version"], patched["current_version"])
        self.assertEqual(selected["workflow"]["mode"], "non_realtime_versioned_edit")
        self.assertEqual(len(selected["recent_events"]), 1)
        self.assertEqual(selected["recent_events"][0]["id"], patched["event_id"])
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._snapshot(model["id"]), before_snapshot)
        assert_replay_matches_latest(self.db_path, model["id"])

    def test_bootstrap_without_selected_document_returns_null_selected_state(self) -> None:
        self._create_document("config/model.json")
        before_events = self._event_count()

        result = get_project_editor_bootstrap(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            include_validation=False,
            recent_events_limit=0,
        )

        self.assertIsNone(result["bootstrap"]["selected_document_id"])
        self.assertFalse(result["bootstrap"]["include_selected_document"])
        self.assertIsNone(result["selected_document_editor_state"])
        self.assertEqual(len(result["documents"]["documents"]), 1)
        self.assertEqual(result["document_tree"]["summary"]["document_count"], 1)
        self.assertEqual(self._event_count(), before_events)

    def test_viewer_bootstrap_is_read_only(self) -> None:
        document = self._create_document("config/viewer.json", {"value": 1})
        before_events = self._event_count()

        result = get_project_editor_bootstrap(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
            selected_document_id=document["id"],
            include_validation=True,
        )

        self.assertEqual(result["actor"]["role"], "viewer")
        self.assertFalse(result["actor"]["capabilities"]["can_patch"])
        selected = result["selected_document_editor_state"]
        self.assertEqual(selected["editor"]["role"], "viewer")
        self.assertEqual(selected["workflow"]["state_machine"]["initial_state"], "read_only")
        self.assertFalse(selected["workflow"]["actions"]["save_content"]["available"])
        self.assertEqual(selected["validation"], {"available": False, "reason": "permission_denied"})
        self.assertEqual(self._event_count(), before_events)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_selected_document_must_belong_to_project_and_be_active(self) -> None:
        document = self._create_document("config/deleted.json")
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )

        with self.assertRaises(AppError) as wrong_project:
            get_project_editor_bootstrap(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                selected_document_id=other_document["id"],
            )
        self.assertEqual(wrong_project.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)

        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )
        before_events = self._event_count()
        with self.assertRaises(AppError) as deleted:
            get_project_editor_bootstrap(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                selected_document_id=document["id"],
            )

        self.assertEqual(deleted.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)
        self.assertEqual(self._event_count(), before_events)
        assert_replay_matches_latest(self.db_path, document["id"])
        assert_replay_matches_latest(self.db_path, other_document["id"])

    def test_validation_and_permission_errors_do_not_mutate(self) -> None:
        self._create_document("config/visible.json")
        invalid_cases = [
            {"recent_events_limit": -1},
            {"recent_events_limit": 51},
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
            {"path_prefix": "config\\bad"},
            {"path_prefix": " config"},
            {"path_prefix": "config//bad"},
            {"q": "bad\\query"},
        ]
        before_events = self._event_count()
        before_documents = self._document_count()

        for kwargs in invalid_cases:
            with self.assertRaises(AppError) as raised:
                get_project_editor_bootstrap(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    **kwargs,
                )
            self.assertEqual(raised.exception.code, ErrorCode.INVALID_REQUEST)
            self.assertEqual(self._event_count(), before_events)
            self.assertEqual(self._document_count(), before_documents)

        with self.assertRaises(AppError) as nonmember:
            get_project_editor_bootstrap(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.nonmember["id"],
            )
        self.assertEqual(nonmember.exception.code, ErrorCode.PERMISSION_DENIED)
        self.assertEqual(self._event_count(), before_events)

    def test_http_route_and_api_token_scope(self) -> None:
        document = self._create_document("config/http.json", {"value": 1})
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other-http.json",
            content={"other": True},
        )
        client = TestClient(create_app(self.db_path))
        token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "bootstrap token"},
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(
            f"/projects/{self.project['id']}/editor-bootstrap",
            headers=headers,
            params={"selected_document_id": document["id"], "path_prefix": "config", "recent_events_limit": 1},
        )
        denied = client.get(
            f"/projects/{self.other_project['id']}/editor-bootstrap",
            headers=headers,
            params={"selected_document_id": other_document["id"]},
        )
        bad_prefix = client.get(
            f"/projects/{self.project['id']}/editor-bootstrap",
            headers=headers,
            params={"path_prefix": "config//bad"},
        )
        bad_selected = client.get(
            f"/projects/{self.project['id']}/editor-bootstrap",
            headers=headers,
            params={"selected_document_id": other_document["id"]},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["project"]["id"], self.project["id"])
        self.assertEqual(body["documents"]["documents"][0]["id"], document["id"])
        self.assertEqual(body["selected_document_editor_state"]["document"]["id"], document["id"])
        self.assertEqual(body["bootstrap"]["actions"]["reload"]["endpoint"], f"/projects/{self.project['id']}/editor-bootstrap")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(bad_prefix.status_code, 400)
        self.assertEqual(bad_prefix.json()["error"]["code"], ErrorCode.INVALID_REQUEST)
        self.assertEqual(bad_selected.status_code, 404)
        self.assertEqual(bad_selected.json()["error"]["code"], ErrorCode.DOCUMENT_NOT_FOUND)

        routes = {(route.path, ",".join(sorted(route.methods))) for route in create_app(self.db_path).routes if hasattr(route, "methods")}
        self.assertIn(("/projects/{project_id}/editor-bootstrap", "GET"), routes)
        assert_replay_matches_latest(self.db_path, document["id"])
        assert_replay_matches_latest(self.db_path, other_document["id"])


if __name__ == "__main__":
    unittest.main()

