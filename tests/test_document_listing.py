from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import create_document, delete_document, list_project_documents
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class DocumentListingTests(unittest.TestCase):
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

    def test_list_active_documents_metadata_order_and_no_content(self) -> None:
        self._create_document("config/zeta.json")
        first = self._create_document("config/alpha.json")
        self._create_document("datasets/items.json")
        before_event_count = self._event_count()
        before_snapshot = self._snapshot(first["id"])

        result = list_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(
            [document["full_path"] for document in result["documents"]],
            ["config/alpha.json", "config/zeta.json", "datasets/items.json"],
        )
        self.assertEqual(result["pagination"], {"limit": 50, "offset": 0, "total": 3, "has_more": False})
        self.assertEqual(result["filters"], {"include_deleted": False, "path_prefix": None, "q": None})
        self.assertNotIn("content", result["documents"][0])
        self.assertEqual(self._event_count(), before_event_count)
        self.assertEqual(self._snapshot(first["id"]), before_snapshot)

    def test_path_query_and_pagination_filters(self) -> None:
        self._create_document("archive/model-old.json")
        self._create_document("config/model.json")
        self._create_document("config/train.json")
        self._create_document("configurations/model.json")
        self._create_document("datasets/model.json")

        prefixed = list_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            path_prefix="config/",
        )
        segment_prefixed = list_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            path_prefix="config",
        )
        queried = list_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="MODEL",
        )
        paged = list_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            limit=2,
            offset=1,
        )

        self.assertEqual([document["full_path"] for document in prefixed["documents"]], ["config/model.json", "config/train.json"])
        self.assertEqual([document["full_path"] for document in segment_prefixed["documents"]], ["config/model.json", "config/train.json"])
        self.assertEqual(prefixed["filters"]["path_prefix"], "config")
        self.assertEqual(
            [document["full_path"] for document in queried["documents"]],
            ["archive/model-old.json", "config/model.json", "configurations/model.json", "datasets/model.json"],
        )
        self.assertEqual([document["full_path"] for document in paged["documents"]], ["config/model.json", "config/train.json"])
        self.assertEqual(paged["pagination"], {"limit": 2, "offset": 1, "total": 5, "has_more": True})

    def test_soft_deleted_documents_are_hidden_by_default_and_optionally_visible(self) -> None:
        active = self._create_document("config/active.json")
        deleted = self._create_document("config/deleted.json")
        delete_document(
            self.db_path,
            document_id=deleted["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )

        default_result = list_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        with_deleted = list_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            include_deleted=True,
        )

        self.assertEqual([document["id"] for document in default_result["documents"]], [active["id"]])
        by_id = {document["id"]: document for document in with_deleted["documents"]}
        self.assertIn(active["id"], by_id)
        self.assertIn(deleted["id"], by_id)
        self.assertIsNotNone(by_id[deleted["id"]]["deleted_at"])
        self.assertEqual(by_id[deleted["id"]]["current_version"], 2)

    def test_list_validation_and_permission_policy(self) -> None:
        self._create_document("config/visible.json")

        viewer_result = list_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
        )
        self.assertEqual(len(viewer_result["documents"]), 1)

        invalid_cases = [
            {"limit": 0},
            {"limit": 101},
            {"offset": -1},
            {"path_prefix": "config\\bad"},
            {"path_prefix": " config"},
            {"path_prefix": "config "},
            {"path_prefix": "/config"},
            {"path_prefix": "config//bad"},
            {"path_prefix": "config//"},
            {"path_prefix": "config/./bad"},
            {"path_prefix": "config/../bad"},
            {"q": "bad\\query"},
        ]
        before_events = self._event_count()
        before_documents = self._document_count()
        for kwargs in invalid_cases:
            with self.assertRaises(AppError) as raised:
                list_project_documents(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    **kwargs,
                )
            self.assertEqual(raised.exception.code, ErrorCode.INVALID_REQUEST)
            self.assertEqual(self._event_count(), before_events)
            self.assertEqual(self._document_count(), before_documents)

        with self.assertRaises(AppError) as nonmember_error:
            list_project_documents(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.nonmember["id"],
            )
        self.assertEqual(nonmember_error.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_http_route_and_api_token_scope(self) -> None:
        self._create_document("config/http.json")
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
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "listing token"},
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]

        listed = client.get(
            f"/projects/{self.project['id']}/documents",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": "http"},
        )
        other_list = client.get(
            f"/projects/{self.other_project['id']}/documents",
            headers={"Authorization": f"Bearer {token}"},
        )
        before_invalid_events = self._event_count()
        before_invalid_documents = self._document_count()
        invalid_prefix = client.get(
            f"/projects/{self.project['id']}/documents",
            headers={"Authorization": f"Bearer {token}"},
            params={"path_prefix": "config//bad"},
        )

        self.assertEqual(listed.status_code, 200)
        self.assertEqual([document["full_path"] for document in listed.json()["documents"]], ["config/http.json"])
        self.assertNotIn("content", listed.json()["documents"][0])
        self.assertEqual(other_list.status_code, 403)
        self.assertEqual(other_list.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(invalid_prefix.status_code, 400)
        self.assertEqual(invalid_prefix.json()["error"]["code"], ErrorCode.INVALID_REQUEST)
        self.assertEqual(self._event_count(), before_invalid_events)
        self.assertEqual(self._document_count(), before_invalid_documents)

    def test_document_list_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/documents", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
