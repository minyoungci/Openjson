from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import assert_replay_matches_latest, create_document
from app.errors import ErrorCode
from app.main import create_app
from app.schema_service import create_schema
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class ApiTokenDocumentValidateTests(unittest.TestCase):
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

    def _client(self) -> TestClient:
        return TestClient(create_app(self.db_path))

    def _create_token(self, client: TestClient, actor_id: str, name: str) -> dict:
        response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": actor_id},
            json={"name": name},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _strict_schema(self) -> dict:
        return create_schema(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name="strict_validate",
            version="1.0.0",
            schema_json={
                "type": "object",
                "required": ["value"],
                "properties": {
                    "value": {"type": "number", "minimum": 10},
                },
                "additionalProperties": False,
            },
        )

    def _bind_document_to_schema(self, document_id: str, schema_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE json_documents SET schema_id = ? WHERE id = ?",
                (schema_id, document_id),
            )

    def _document_state(self, document_id: str) -> dict:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT current_version, current_snapshot_json
                FROM json_documents
                WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
            event_count = conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]
        return {
            "current_version": row["current_version"],
            "content": json.loads(row["current_snapshot_json"]),
            "event_count": event_count,
        }

    def test_bearer_token_validate_returns_results_without_mutating_documents(self) -> None:
        schema = self._strict_schema()
        valid_document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/valid.json",
            schema_id=schema["id"],
            content={"value": 10},
        )
        invalid_document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="legacy/invalid.json",
            content={"value": 1},
        )
        self._bind_document_to_schema(invalid_document["id"], schema["id"])
        unbound_document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="misc/free.json",
            content={"free": True},
        )
        before = {
            document["id"]: self._document_state(document["id"])
            for document in [valid_document, invalid_document, unbound_document]
        }
        client = self._client()
        created_token = self._create_token(client, self.owner["id"], "validate token")
        bearer_headers = {"Authorization": f"Bearer {created_token['token']}"}

        valid_response = client.post(f"/documents/{valid_document['id']}/validate", headers=bearer_headers)
        invalid_response = client.post(f"/documents/{invalid_document['id']}/validate", headers=bearer_headers)
        unbound_response = client.post(f"/documents/{unbound_document['id']}/validate", headers=bearer_headers)

        self.assertEqual(valid_response.status_code, 200)
        self.assertTrue(valid_response.json()["valid"])
        self.assertEqual(valid_response.json()["project_id"], self.project["id"])
        self.assertEqual(valid_response.json()["full_path"], "config/valid.json")
        self.assertEqual(valid_response.json()["current_version"], 1)
        self.assertIsNone(valid_response.json()["deleted_at"])
        self.assertEqual(valid_response.json()["schema_id"], schema["id"])
        self.assertEqual(valid_response.json()["errors"], [])

        self.assertEqual(invalid_response.status_code, 200)
        self.assertFalse(invalid_response.json()["valid"])
        self.assertEqual(invalid_response.json()["project_id"], self.project["id"])
        self.assertEqual(invalid_response.json()["full_path"], "legacy/invalid.json")
        self.assertEqual(invalid_response.json()["current_version"], 1)
        self.assertEqual(invalid_response.json()["schema_id"], schema["id"])
        self.assertEqual(invalid_response.json()["errors"][0]["path"], "/value")
        self.assertEqual(invalid_response.json()["errors"][0]["validator"], "minimum")

        self.assertEqual(unbound_response.status_code, 200)
        self.assertTrue(unbound_response.json()["valid"])
        self.assertEqual(unbound_response.json()["project_id"], self.project["id"])
        self.assertEqual(unbound_response.json()["full_path"], "misc/free.json")
        self.assertEqual(unbound_response.json()["current_version"], 1)
        self.assertIsNone(unbound_response.json()["schema_id"])
        self.assertEqual(unbound_response.json()["warnings"][0]["path"], "")

        after = {
            document["id"]: self._document_state(document["id"])
            for document in [valid_document, invalid_document, unbound_document]
        }
        self.assertEqual(after, before)
        for document in [valid_document, invalid_document, unbound_document]:
            assert_replay_matches_latest(self.db_path, document["id"])

    def test_bearer_token_validate_enforces_project_scope_and_validate_permission(self) -> None:
        schema = self._strict_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/scoped.json",
            schema_id=schema["id"],
            content={"value": 10},
        )
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"value": 10},
        )
        client = self._client()
        owner_token = self._create_token(client, self.owner["id"], "owner validate token")
        viewer_token = self._create_token(client, self.viewer["id"], "viewer validate token")

        cross_project_response = client.post(
            f"/documents/{other_document['id']}/validate",
            headers={"Authorization": f"Bearer {owner_token['token']}"},
        )
        viewer_response = client.post(
            f"/documents/{document['id']}/validate",
            headers={"Authorization": f"Bearer {viewer_token['token']}"},
        )

        self.assertEqual(cross_project_response.status_code, 403)
        self.assertEqual(cross_project_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(viewer_response.status_code, 403)
        self.assertEqual(viewer_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(self._document_state(document["id"])["event_count"], 1)
        self.assertEqual(self._document_state(other_document["id"])["event_count"], 1)
        assert_replay_matches_latest(self.db_path, document["id"])
        assert_replay_matches_latest(self.db_path, other_document["id"])


if __name__ == "__main__":
    unittest.main()
