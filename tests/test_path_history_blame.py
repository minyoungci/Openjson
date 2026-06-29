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
    get_document_path_blame,
    get_document_path_history,
    patch_document,
    rollback_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class PathHistoryBlameTests(unittest.TestCase):
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

    def _create_document(self) -> dict:
        return create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/model.json",
            content={"model": {"name": "baseline"}, "learning_rate": 0.001, "obsolete": True},
        )

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _current_snapshot(self, document_id: str) -> object:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        return json.loads(row["current_snapshot_json"])

    def test_path_history_tracks_create_update_and_rollback_without_unrelated_events(self) -> None:
        document = self._create_document()
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=2,
            patch=[{"op": "add", "path": "/optimizer", "value": "adam"}],
        )
        rollback_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=3,
            target_version=1,
        )
        before_count = self._event_count(document["id"])
        before_snapshot = self._current_snapshot(document["id"])

        history = get_document_path_history(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            path="/learning_rate",
        )
        blame = get_document_path_blame(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            path="/learning_rate",
        )

        self.assertEqual([change["event_type"] for change in history["changes"]], ["create", "update", "rollback"])
        self.assertEqual([change["result_version"] for change in history["changes"]], [1, 2, 4])
        self.assertEqual(history["changes"][0]["before"], {"exists": False, "value": None})
        self.assertEqual(history["changes"][0]["after"], {"exists": True, "value": 0.001})
        self.assertEqual(history["changes"][1]["before"]["value"], 0.001)
        self.assertEqual(history["changes"][1]["after"]["value"], 0.0005)
        self.assertEqual(history["latest"], {"exists": True, "value": 0.001})
        self.assertEqual(history["blame"]["event_type"], "rollback")
        self.assertEqual(blame["blame"], history["blame"])
        self.assertEqual(self._event_count(document["id"]), before_count)
        self.assertEqual(self._current_snapshot(document["id"]), before_snapshot)

    def test_parent_replace_json_pointer_escaping_missing_and_root_paths(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/pointers.json",
            content={"model": {"name": "baseline"}, "a/b": 1, "c~d": 2},
        )
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[
                {"op": "replace", "path": "/model", "value": {"name": "candidate"}},
                {"op": "replace", "path": "/a~1b", "value": 10},
                {"op": "replace", "path": "/c~0d", "value": 20},
            ],
        )

        child_history = get_document_path_history(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            path="/model/name",
        )
        escaped_slash = get_document_path_history(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            path="/a~1b",
        )
        escaped_tilde = get_document_path_history(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            path="/c~0d",
        )
        missing = get_document_path_history(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            path="/missing",
        )
        root = get_document_path_history(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            path="",
        )

        self.assertEqual([change["result_version"] for change in child_history["changes"]], [1, 2])
        self.assertEqual(child_history["latest"], {"exists": True, "value": "candidate"})
        self.assertEqual(escaped_slash["latest"], {"exists": True, "value": 10})
        self.assertEqual(escaped_tilde["latest"], {"exists": True, "value": 20})
        self.assertEqual(missing["changes"], [])
        self.assertEqual(missing["latest"], {"exists": False, "value": None})
        self.assertEqual([change["event_type"] for change in root["changes"]], ["create", "update"])

    def test_soft_deleted_document_history_and_permission_policy(self) -> None:
        document = self._create_document()
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )

        viewer_history = get_document_path_history(
            self.db_path,
            document_id=document["id"],
            actor_id=self.viewer["id"],
            path="/learning_rate",
        )

        self.assertIsNotNone(viewer_history["deleted_at"])
        self.assertEqual([change["event_type"] for change in viewer_history["changes"]], ["create"])

        with self.assertRaises(AppError) as invalid_path:
            get_document_path_history(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                path="learning_rate",
            )
        self.assertEqual(invalid_path.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(AppError) as invalid_escape_history:
            get_document_path_history(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                path="/learning_rate~2",
            )
        self.assertEqual(invalid_escape_history.exception.code, ErrorCode.INVALID_REQUEST)
        self.assertIn("Invalid JSON Pointer escape sequence", invalid_escape_history.exception.details["message"])

        with self.assertRaises(AppError) as invalid_escape_blame:
            get_document_path_blame(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                path="/learning_rate~",
            )
        self.assertEqual(invalid_escape_blame.exception.code, ErrorCode.INVALID_REQUEST)
        self.assertIn("JSON Pointer escape sequence", invalid_escape_blame.exception.details["message"])
        self.assertEqual(self._event_count(document["id"]), 2)
        self.assertEqual(self._current_snapshot(document["id"])["learning_rate"], 0.001)

        with self.assertRaises(AppError) as nonmember:
            get_document_path_blame(
                self.db_path,
                document_id=document["id"],
                actor_id=self.nonmember["id"],
                path="/learning_rate",
            )
        self.assertEqual(nonmember.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_http_routes_and_api_token_scope(self) -> None:
        document = self._create_document()
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"learning_rate": 1},
        )
        client = TestClient(create_app(self.db_path))
        token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "path history token"},
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]

        history_response = client.get(
            f"/documents/{document['id']}/path-history",
            headers={"Authorization": f"Bearer {token}"},
            params={"path": "/learning_rate"},
        )
        blame_response = client.get(
            f"/documents/{document['id']}/blame",
            headers={"Authorization": f"Bearer {token}"},
            params={"path": "/learning_rate"},
        )
        other_response = client.get(
            f"/documents/{other_document['id']}/path-history",
            headers={"Authorization": f"Bearer {token}"},
            params={"path": "/learning_rate"},
        )

        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(history_response.json()["changes"][0]["event_type"], "create")
        self.assertEqual(blame_response.status_code, 200)
        self.assertEqual(blame_response.json()["blame"]["event_type"], "create")
        self.assertEqual(other_response.status_code, 403)
        self.assertEqual(other_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

    def test_path_history_routes_are_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/documents/{document_id}/path-history", "GET"), routes)
        self.assertIn(("/documents/{document_id}/blame", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
