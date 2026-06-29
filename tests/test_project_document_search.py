from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import create_document, delete_document, search_project_documents
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class ProjectDocumentSearchTests(unittest.TestCase):
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

    def _create_model_document(self) -> dict:
        return create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/model.json",
            content={
                "learning_rate": 0.001,
                "enabled": True,
                "optimizer": {"name": "Adam"},
                "datasets": [{"name": "ADNI"}],
                "a/b": {"c~d": "escaped marker"},
            },
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

    def test_search_matches_full_path_keys_values_arrays_and_escaped_paths_without_mutation(self) -> None:
        document = self._create_model_document()
        before_events = self._event_count()
        before_snapshot = self._snapshot(document["id"])

        full_path = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="MODEL",
        )
        key = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="learning",
        )
        value = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="adam",
        )
        array_value = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="adni",
        )
        escaped = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="marker",
        )

        self.assertEqual(full_path["documents"][0]["matches"][0]["match_type"], "full_path")
        self.assertEqual(key["documents"][0]["matches"][0]["path"], "/learning_rate")
        self.assertEqual(key["documents"][0]["matches"][0]["match_type"], "key")
        self.assertEqual(value["documents"][0]["matches"][0]["path"], "/optimizer/name")
        self.assertEqual(value["documents"][0]["matches"][0]["value"], "Adam")
        self.assertEqual(array_value["documents"][0]["matches"][0]["path"], "/datasets/0/name")
        self.assertEqual(escaped["documents"][0]["matches"][0]["path"], "/a~1b/c~0d")
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._snapshot(document["id"]), before_snapshot)

    def test_path_restriction_root_path_and_missing_subtree_policy(self) -> None:
        self._create_model_document()

        nested = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="adam",
            path="/optimizer",
        )
        wrong_subtree = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="adam",
            path="/datasets",
        )
        root = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="true",
            path="",
        )
        missing = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="adam",
            path="/missing",
        )

        self.assertEqual(nested["pagination"]["total"], 1)
        self.assertEqual(nested["documents"][0]["matches"][0]["path"], "/optimizer/name")
        self.assertEqual(wrong_subtree["documents"], [])
        self.assertEqual(root["documents"][0]["matches"][0]["path"], "/enabled")
        self.assertEqual(missing["documents"], [])

    def test_soft_deleted_documents_are_hidden_by_default_and_optionally_visible(self) -> None:
        document = self._create_model_document()
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )

        hidden = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="adam",
        )
        visible = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="adam",
            include_deleted=True,
        )

        self.assertEqual(hidden["documents"], [])
        self.assertEqual(visible["pagination"]["total"], 1)
        self.assertEqual(visible["documents"][0]["id"], document["id"])
        self.assertIsNotNone(visible["documents"][0]["deleted_at"])

    def test_pagination_and_per_document_match_truncation(self) -> None:
        create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/a.json",
            content={"first": "needle", "second": "needle", "nested": {"third": "needle"}},
        )
        create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/b.json",
            content={"first": "needle"},
        )

        result = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="needle",
            limit=1,
            offset=0,
            max_matches_per_document=1,
        )

        self.assertEqual(result["pagination"], {"limit": 1, "offset": 0, "total": 2, "has_more": True})
        self.assertEqual(result["filters"], {"q": "needle", "path": None, "include_deleted": False, "max_matches_per_document": 1})
        self.assertEqual(result["documents"][0]["match_count"], 3)
        self.assertTrue(result["documents"][0]["matches_truncated"])
        self.assertEqual(len(result["documents"][0]["matches"]), 1)

    def test_validation_and_permission_policy(self) -> None:
        self._create_model_document()

        invalid_cases = [
            {"q": ""},
            {"q": "   "},
            {"q": "adam", "path": "optimizer"},
            {"q": "adam", "path": "/optimizer~2name"},
            {"q": "adam", "path": "/optimizer~"},
            {"q": "adam", "limit": 0},
            {"q": "adam", "limit": 101},
            {"q": "adam", "offset": -1},
            {"q": "adam", "max_matches_per_document": 0},
            {"q": "adam", "max_matches_per_document": 21},
        ]
        for kwargs in invalid_cases:
            with self.assertRaises(AppError) as raised:
                search_project_documents(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    **kwargs,
                )
            self.assertEqual(raised.exception.code, ErrorCode.INVALID_REQUEST)

        self.assertEqual(self._event_count(), 1)

        viewer_result = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
            q="adam",
        )
        self.assertEqual(viewer_result["pagination"]["total"], 1)

        with self.assertRaises(AppError) as nonmember_error:
            search_project_documents(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.nonmember["id"],
                q="adam",
            )
        self.assertEqual(nonmember_error.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_http_route_and_api_token_scope(self) -> None:
        document = self._create_model_document()
        create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"optimizer": {"name": "Adam"}},
        )
        client = TestClient(create_app(self.db_path))
        token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "search token"},
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]

        searched = client.get(
            f"/projects/{self.project['id']}/document-search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": "adam", "path": "/optimizer"},
        )
        other_search = client.get(
            f"/projects/{self.other_project['id']}/document-search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": "adam"},
        )
        missing_q = client.get(
            f"/projects/{self.project['id']}/document-search",
            headers={"Authorization": f"Bearer {token}"},
        )
        before_invalid_count = self._event_count()
        before_invalid_snapshot = self._snapshot(document["id"])
        invalid_paths = [
            client.get(
                f"/projects/{self.project['id']}/document-search",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": "adam", "path": bad_path},
            )
            for bad_path in ("/optimizer~2name", "/optimizer~")
        ]

        self.assertEqual(searched.status_code, 200)
        body = searched.json()
        self.assertEqual(body["pagination"]["total"], 1)
        self.assertEqual(body["documents"][0]["id"], document["id"])
        self.assertEqual(body["documents"][0]["matches"][0]["path"], "/optimizer/name")
        self.assertEqual(other_search.status_code, 403)
        self.assertEqual(other_search.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(missing_q.status_code, 400)
        self.assertEqual(missing_q.json()["error"]["code"], ErrorCode.INVALID_REQUEST)
        for response in invalid_paths:
            self.assertEqual(response.status_code, 400)
            error = response.json()["error"]
            self.assertEqual(error["code"], ErrorCode.INVALID_REQUEST)
            self.assertIn("JSON Pointer", error["details"]["message"])
        self.assertEqual(self._event_count(), before_invalid_count)
        self.assertEqual(self._snapshot(document["id"]), before_invalid_snapshot)

    def test_document_search_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/document-search", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
