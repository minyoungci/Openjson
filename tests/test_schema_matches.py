from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.schema_match_service import preview_project_schema_matches
from app.schema_service import create_schema
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class SchemaMatchPreviewTests(unittest.TestCase):
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

    def _schema(self, name: str, file_pattern: str) -> dict:
        return create_schema(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name=name,
            version="1",
            file_pattern=file_pattern,
            schema_json={"type": "object"},
        )

    def _counts(self) -> dict[str, int]:
        with connect(self.db_path) as conn:
            return {
                "schemas": conn.execute("SELECT COUNT(*) AS count FROM schemas").fetchone()["count"],
                "documents": conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"],
                "document_events": conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"],
                "audit_log": conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"],
            }

    def test_preview_reports_no_match_one_match_and_no_schema_json_without_mutation(self) -> None:
        config_schema = self._schema("config", "config/*.json")
        self._schema("datasets", "datasets/*.json")
        before_counts = self._counts()

        matched = preview_project_schema_matches(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
            full_path="config/model.json",
        )
        no_match = preview_project_schema_matches(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
            full_path="notes/readme.json",
        )

        self.assertEqual(matched["project_id"], self.project["id"])
        self.assertEqual(matched["full_path"], "config/model.json")
        self.assertEqual(matched["match_count"], 1)
        self.assertEqual(matched["resolution"], {"status": "matched", "schema_id": config_schema["id"]})
        self.assertEqual(matched["matches"][0]["id"], config_schema["id"])
        self.assertEqual(matched["matches"][0]["file_pattern"], "config/*.json")
        self.assertNotIn("schema", matched["matches"][0])
        self.assertEqual(no_match["match_count"], 0)
        self.assertEqual(no_match["resolution"], {"status": "no_match", "schema_id": None})
        self.assertEqual(no_match["matches"], [])
        self.assertEqual(self._counts(), before_counts)

    def test_preview_uses_case_sensitive_file_pattern_matching(self) -> None:
        config_schema = self._schema("config", "config/*.json")
        before_counts = self._counts()

        matched = preview_project_schema_matches(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
            full_path="config/model.json",
        )
        case_mismatch = preview_project_schema_matches(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
            full_path="CONFIG/model.json",
        )

        self.assertEqual(matched["resolution"], {"status": "matched", "schema_id": config_schema["id"]})
        self.assertEqual(case_mismatch["match_count"], 0)
        self.assertEqual(case_mismatch["resolution"], {"status": "no_match", "schema_id": None})
        self.assertEqual(case_mismatch["matches"], [])
        self.assertEqual(self._counts(), before_counts)

    def test_ambiguous_and_nested_fnmatch_policy(self) -> None:
        broad = self._schema("config", "config/*.json")
        specific = self._schema("specific", "config/model.json")

        ambiguous = preview_project_schema_matches(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/model.json",
        )
        nested = preview_project_schema_matches(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/nested/model.json",
        )

        self.assertEqual(ambiguous["match_count"], 2)
        self.assertEqual(ambiguous["resolution"]["status"], "ambiguous")
        self.assertEqual(ambiguous["resolution"]["schema_id"], None)
        self.assertEqual(set(ambiguous["resolution"]["schema_ids"]), {broad["id"], specific["id"]})
        self.assertEqual([match["id"] for match in nested["matches"]], [broad["id"]])
        self.assertEqual(nested["resolution"], {"status": "matched", "schema_id": broad["id"]})

    def test_validation_and_permission_policy(self) -> None:
        self._schema("config", "config/*.json")
        before_invalid_counts = self._counts()
        invalid_paths = (
            None,
            "",
            "   ",
            " config/model.json",
            "config/model.json ",
            "config\\model.json",
            "/config/model.json",
            "config/model.json/",
            "config//model.json",
            "config/./model.json",
            "config/../model.json",
        )
        for full_path in invalid_paths:
            with self.assertRaises(AppError) as raised:
                preview_project_schema_matches(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    full_path=full_path,
                )
            self.assertEqual(raised.exception.code, ErrorCode.INVALID_REQUEST)
            self.assertEqual(self._counts(), before_invalid_counts)

        viewer_result = preview_project_schema_matches(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
            full_path="config/model.json",
        )
        self.assertEqual(viewer_result["match_count"], 1)

        with self.assertRaises(AppError) as nonmember_error:
            preview_project_schema_matches(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.nonmember["id"],
                full_path="config/model.json",
            )
        self.assertEqual(nonmember_error.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as missing_actor:
            preview_project_schema_matches(
                self.db_path,
                project_id=self.project["id"],
                actor_id=None,
                full_path="config/model.json",
            )
        self.assertEqual(missing_actor.exception.code, ErrorCode.AUTH_REQUIRED)

    def test_http_route_and_api_token_scope(self) -> None:
        schema = self._schema("config", "config/*.json")
        create_schema(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            name="other",
            version="1",
            file_pattern="config/*.json",
            schema_json={"type": "object"},
        )
        client = TestClient(create_app(self.db_path))
        token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.viewer["id"]},
            json={"name": "schema match token"},
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]

        matched = client.get(
            f"/projects/{self.project['id']}/schema-matches",
            headers={"Authorization": f"Bearer {token}"},
            params={"full_path": "config/model.json"},
        )
        case_mismatch = client.get(
            f"/projects/{self.project['id']}/schema-matches",
            headers={"Authorization": f"Bearer {token}"},
            params={"full_path": "CONFIG/model.json"},
        )
        other_project = client.get(
            f"/projects/{self.other_project['id']}/schema-matches",
            headers={"Authorization": f"Bearer {token}"},
            params={"full_path": "config/model.json"},
        )
        before_invalid_counts = self._counts()
        invalid_path = client.get(
            f"/projects/{self.project['id']}/schema-matches",
            headers={"Authorization": f"Bearer {token}"},
            params={"full_path": "config//model.json"},
        )

        self.assertEqual(matched.status_code, 200)
        self.assertEqual(matched.json()["resolution"], {"status": "matched", "schema_id": schema["id"]})
        self.assertNotIn("schema", matched.json()["matches"][0])
        self.assertEqual(case_mismatch.status_code, 200)
        self.assertEqual(case_mismatch.json()["resolution"], {"status": "no_match", "schema_id": None})
        self.assertEqual(case_mismatch.json()["matches"], [])
        self.assertEqual(other_project.status_code, 403)
        self.assertEqual(other_project.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(invalid_path.status_code, 400)
        self.assertEqual(invalid_path.json()["error"]["code"], ErrorCode.INVALID_REQUEST)
        self.assertEqual(self._counts(), before_invalid_counts)

    def test_schema_match_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/schema-matches", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
