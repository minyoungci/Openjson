from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import create_document, delete_document, get_project_document_tree
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class ProjectDocumentTreeTests(unittest.TestCase):
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

    def _create_document(self, full_path: str) -> dict:
        return create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path=full_path,
            content={"path": full_path},
        )

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

    def _document_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"]

    def test_tree_represents_nested_folders_root_documents_and_no_content_without_mutation(self) -> None:
        root_doc = self._create_document("README.json")
        config_doc = self._create_document("config/model.json")
        self._create_document("config/train/params.json")
        self._create_document("datasets/raw/items.json")
        before_events = self._event_count()
        before_snapshot = self._snapshot(config_doc["id"])

        result = get_project_document_tree(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(result["summary"], {"document_count": 4, "folder_count": 4, "deleted_document_count": 0})
        self.assertEqual(result["filters"], {"include_deleted": False, "path_prefix": None})
        self.assertEqual(result["root"]["path"], "")
        self.assertEqual(result["root"]["document_count"], 4)
        self.assertEqual([child["name"] for child in result["root"]["children"]], ["config", "datasets", "README.json"])
        config = result["root"]["children"][0]
        datasets = result["root"]["children"][1]
        readme = result["root"]["children"][2]
        self.assertEqual(config["type"], "folder")
        self.assertEqual(config["path"], "config")
        self.assertEqual(config["document_count"], 2)
        self.assertEqual([child["name"] for child in config["children"]], ["train", "model.json"])
        self.assertEqual(config["children"][1]["document"]["id"], config_doc["id"])
        self.assertNotIn("content", config["children"][1]["document"])
        self.assertEqual(datasets["children"][0]["path"], "datasets/raw")
        self.assertEqual(readme["type"], "document")
        self.assertEqual(readme["path"], "README.json")
        self.assertEqual(readme["document"]["id"], root_doc["id"])
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._snapshot(config_doc["id"]), before_snapshot)

    def test_path_prefix_roots_tree_at_virtual_folder(self) -> None:
        self._create_document("README.json")
        model = self._create_document("config/model.json")
        self._create_document("config/train/params.json")
        self._create_document("datasets/raw/items.json")

        result = get_project_document_tree(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            path_prefix="config/",
        )

        self.assertEqual(result["root"]["name"], "config")
        self.assertEqual(result["root"]["path"], "config")
        self.assertEqual(result["summary"], {"document_count": 2, "folder_count": 1, "deleted_document_count": 0})
        self.assertEqual([child["name"] for child in result["root"]["children"]], ["train", "model.json"])
        self.assertEqual(result["root"]["children"][1]["path"], "config/model.json")
        self.assertEqual(result["root"]["children"][1]["document"]["id"], model["id"])
        self.assertEqual(result["filters"], {"include_deleted": False, "path_prefix": "config"})

    def test_soft_deleted_documents_hidden_by_default_and_optionally_included(self) -> None:
        active = self._create_document("config/active.json")
        deleted = self._create_document("config/deleted.json")
        delete_document(
            self.db_path,
            document_id=deleted["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )

        default_result = get_project_document_tree(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        with_deleted = get_project_document_tree(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            include_deleted=True,
        )

        default_config = default_result["root"]["children"][0]
        full_config = with_deleted["root"]["children"][0]
        self.assertEqual([child["document"]["id"] for child in default_config["children"]], [active["id"]])
        exported = {child["document"]["id"]: child["document"] for child in full_config["children"]}
        self.assertIn(active["id"], exported)
        self.assertIn(deleted["id"], exported)
        self.assertIsNotNone(exported[deleted["id"]]["deleted_at"])
        self.assertEqual(with_deleted["summary"]["deleted_document_count"], 1)

    def test_tree_validation_and_permission_policy(self) -> None:
        self._create_document("config/visible.json")
        viewer_result = get_project_document_tree(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
        )
        self.assertEqual(viewer_result["summary"]["document_count"], 1)

        invalid_prefixes = (
            "config\\bad",
            " config",
            "config ",
            "/config",
            "config//bad",
            "config//",
            "config/./bad",
            "config/../bad",
        )
        before_events = self._event_count()
        before_documents = self._document_count()
        for path_prefix in invalid_prefixes:
            with self.assertRaises(AppError) as invalid_prefix:
                get_project_document_tree(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    path_prefix=path_prefix,
                )
            self.assertEqual(invalid_prefix.exception.code, ErrorCode.INVALID_REQUEST)
            self.assertEqual(self._event_count(), before_events)
            self.assertEqual(self._document_count(), before_documents)

        with self.assertRaises(AppError) as nonmember_error:
            get_project_document_tree(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.nonmember["id"],
            )
        self.assertEqual(nonmember_error.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_http_route_and_api_token_scope(self) -> None:
        document = self._create_document("config/http.json")
        create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )
        client = TestClient(create_app(self.db_path))
        token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.viewer["id"]},
            json={"name": "tree token"},
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]

        tree = client.get(
            f"/projects/{self.project['id']}/document-tree",
            headers={"Authorization": f"Bearer {token}"},
            params={"path_prefix": "config"},
        )
        other_tree = client.get(
            f"/projects/{self.other_project['id']}/document-tree",
            headers={"Authorization": f"Bearer {token}"},
        )
        before_invalid_events = self._event_count()
        before_invalid_documents = self._document_count()
        invalid_prefix = client.get(
            f"/projects/{self.project['id']}/document-tree",
            headers={"Authorization": f"Bearer {token}"},
            params={"path_prefix": "config//bad"},
        )

        self.assertEqual(tree.status_code, 200)
        self.assertEqual(tree.json()["root"]["children"][0]["document"]["id"], document["id"])
        self.assertNotIn("content", tree.json()["root"]["children"][0]["document"])
        self.assertEqual(other_tree.status_code, 403)
        self.assertEqual(other_tree.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(invalid_prefix.status_code, 400)
        self.assertEqual(invalid_prefix.json()["error"]["code"], ErrorCode.INVALID_REQUEST)
        self.assertEqual(self._event_count(), before_invalid_events)
        self.assertEqual(self._document_count(), before_invalid_documents)

    def test_document_tree_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/document-tree", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
