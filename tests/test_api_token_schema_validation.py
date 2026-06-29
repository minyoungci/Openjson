from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import assert_replay_matches_latest
from app.errors import ErrorCode
from app.main import create_app
from app.schema_service import create_schema
from app.workspace_service import create_project, create_user, create_workspace


class ApiTokenSchemaValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _client(self) -> TestClient:
        return TestClient(create_app(self.db_path))

    def _create_token(self, client: TestClient) -> dict:
        response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "schema validation token"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _strict_schema(self) -> dict:
        return create_schema(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name="strict_config",
            version="1.0.0",
            file_pattern="config/*.json",
            schema_json={
                "type": "object",
                "required": ["value"],
                "properties": {
                    "value": {"type": "number", "minimum": 10},
                },
                "additionalProperties": False,
            },
        )

    def _total_document_event_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]

    def _document_event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _document_count_by_path(self, full_path: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM json_documents WHERE project_id = ? AND full_path = ?",
                (self.project["id"], full_path),
            ).fetchone()["count"]

    def _document_row(self, document_id: str):
        with connect(self.db_path) as conn:
            return conn.execute(
                """
                SELECT current_version, current_snapshot_json, deleted_at, schema_id
                FROM json_documents
                WHERE id = ?
                """,
                (document_id,),
            ).fetchone()

    def _bind_document_to_schema(self, document_id: str, schema_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE json_documents SET schema_id = ? WHERE id = ?",
                (schema_id, document_id),
            )

    def test_bearer_token_schema_invalid_create_inserts_no_document_or_event(self) -> None:
        self._strict_schema()
        client = self._client()
        created_token = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created_token['token']}"}

        response = client.post(
            f"/projects/{self.project['id']}/documents",
            headers=bearer_headers,
            json={
                "full_path": "config/invalid.json",
                "content": {"value": 1},
            },
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(error["details"]["errors"][0]["path"], "/value")
        self.assertEqual(error["details"]["errors"][0]["validator"], "minimum")
        self.assertEqual(self._document_count_by_path("config/invalid.json"), 0)
        self.assertEqual(self._total_document_event_count(), 0)

    def test_bearer_token_schema_invalid_patch_preserves_event_snapshot_and_version(self) -> None:
        schema = self._strict_schema()
        client = self._client()
        created_token = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created_token['token']}"}

        created_document = client.post(
            f"/projects/{self.project['id']}/documents",
            headers=bearer_headers,
            json={
                "full_path": "config/valid.json",
                "content": {"value": 10},
            },
        )
        self.assertEqual(created_document.status_code, 200)
        document_id = created_document.json()["id"]
        self.assertEqual(created_document.json()["schema_id"], schema["id"])
        self.assertEqual(created_document.json()["current_version"], 1)
        self.assertEqual(self._document_event_count(document_id), 1)

        response = client.patch(
            f"/documents/{document_id}",
            headers=bearer_headers,
            json={
                "base_version": 1,
                "patch": [{"op": "replace", "path": "/value", "value": 1}],
                "reason": "invalid token schema patch",
            },
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(error["details"]["errors"][0]["path"], "/value")
        self.assertEqual(error["details"]["errors"][0]["validator"], "minimum")

        row = self._document_row(document_id)
        self.assertEqual(row["current_version"], 1)
        self.assertEqual(json.loads(row["current_snapshot_json"]), {"value": 10})
        self.assertEqual(self._document_event_count(document_id), 1)
        assert_replay_matches_latest(self.db_path, document_id)

    def test_bearer_token_schema_invalid_restore_preserves_deleted_state_event_and_version(self) -> None:
        schema = self._strict_schema()
        client = self._client()
        created_token = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created_token['token']}"}

        created_document = client.post(
            f"/projects/{self.project['id']}/documents",
            headers=bearer_headers,
            json={
                "full_path": "legacy/restore.json",
                "content": {"value": 1},
            },
        )
        self.assertEqual(created_document.status_code, 200)
        document_id = created_document.json()["id"]

        deleted_document = client.request(
            "DELETE",
            f"/documents/{document_id}",
            headers=bearer_headers,
            json={"base_version": 1, "reason": "prepare invalid restore"},
        )
        self.assertEqual(deleted_document.status_code, 200)
        self.assertEqual(deleted_document.json()["current_version"], 2)
        self.assertIsNotNone(deleted_document.json()["deleted_at"])
        self._bind_document_to_schema(document_id, schema["id"])

        response = client.post(
            f"/documents/{document_id}/restore",
            headers=bearer_headers,
            json={"base_version": 2, "reason": "invalid token schema restore"},
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(error["details"]["errors"][0]["path"], "/value")
        self.assertEqual(error["details"]["errors"][0]["validator"], "minimum")

        row = self._document_row(document_id)
        self.assertEqual(row["current_version"], 2)
        self.assertIsNotNone(row["deleted_at"])
        self.assertEqual(json.loads(row["current_snapshot_json"]), {"value": 1})
        self.assertEqual(self._document_event_count(document_id), 2)
        assert_replay_matches_latest(self.db_path, document_id)

    def test_bearer_token_schema_invalid_rollback_preserves_event_snapshot_and_version(self) -> None:
        schema = self._strict_schema()
        client = self._client()
        created_token = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created_token['token']}"}

        created_document = client.post(
            f"/projects/{self.project['id']}/documents",
            headers=bearer_headers,
            json={
                "full_path": "legacy/rollback.json",
                "content": {"value": 1},
            },
        )
        self.assertEqual(created_document.status_code, 200)
        document_id = created_document.json()["id"]

        patched_document = client.patch(
            f"/documents/{document_id}",
            headers=bearer_headers,
            json={
                "base_version": 1,
                "patch": [{"op": "replace", "path": "/value", "value": 10}],
                "reason": "prepare invalid rollback",
            },
        )
        self.assertEqual(patched_document.status_code, 200)
        self.assertEqual(patched_document.json()["current_version"], 2)
        self.assertEqual(patched_document.json()["content"], {"value": 10})
        self._bind_document_to_schema(document_id, schema["id"])

        response = client.post(
            f"/documents/{document_id}/rollback",
            headers=bearer_headers,
            json={
                "base_version": 2,
                "target_version": 1,
                "reason": "invalid token schema rollback",
            },
        )

        self.assertEqual(response.status_code, 400)
        error = response.json()["error"]
        self.assertEqual(error["code"], ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(error["details"]["errors"][0]["path"], "/value")
        self.assertEqual(error["details"]["errors"][0]["validator"], "minimum")

        row = self._document_row(document_id)
        self.assertEqual(row["current_version"], 2)
        self.assertEqual(json.loads(row["current_snapshot_json"]), {"value": 10})
        self.assertEqual(self._document_event_count(document_id), 2)
        assert_replay_matches_latest(self.db_path, document_id)


if __name__ == "__main__":
    unittest.main()
