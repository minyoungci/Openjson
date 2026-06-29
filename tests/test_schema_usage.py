from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db, utc_now
from app.document_service import create_document, delete_document
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.schema_service import create_schema
from app.schema_usage_service import get_schema_usage
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class SchemaUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.admin = create_user(self.db_path, email="admin@example.com", display_name="Admin")
        self.editor = create_user(self.db_path, email="editor@example.com", display_name="Editor")
        self.reviewer = create_user(self.db_path, email="reviewer@example.com", display_name="Reviewer")
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
        for user, role in (
            (self.admin, "admin"),
            (self.editor, "editor"),
            (self.reviewer, "reviewer"),
            (self.viewer, "viewer"),
        ):
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=user["id"],
                role=role,
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _number_schema(self) -> dict:
        return create_schema(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name="number-value",
            version="1",
            schema_json={
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "number", "minimum": 10}},
                "additionalProperties": True,
            },
        )

    def _invalid_schema(self) -> dict:
        now = utc_now()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO schemas (
                    id,
                    project_id,
                    name,
                    version,
                    schema_json,
                    file_pattern,
                    is_active,
                    created_by,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, 1, ?, ?)
                """,
                (
                    "schema_invalid_json_schema",
                    self.project["id"],
                    "invalid-json-schema",
                    "1",
                    json.dumps({"type": 1}, separators=(",", ":")),
                    self.owner["id"],
                    now,
                ),
            )
        return {"id": "schema_invalid_json_schema", "project_id": self.project["id"]}

    def _bind_schema_directly(self, document_id: str, schema_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET schema_id = ?
                WHERE id = ?
                """,
                (schema_id, document_id),
            )

    def _event_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]

    def _audit_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"]

    def _snapshot(self, document_id: str) -> object:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        return json.loads(row["current_snapshot_json"])

    def test_usage_summarizes_bound_documents_without_content_or_mutation(self) -> None:
        schema = self._number_schema()
        valid_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/valid.json",
            schema_id=schema["id"],
            content={"value": 20},
        )
        invalid_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/invalid.json",
            content={"value": 1},
        )
        self._bind_schema_directly(invalid_doc["id"], schema["id"])
        create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="misc/unbound.json",
            content={"value": 1},
        )
        before_events = self._event_count()
        before_audit = self._audit_count()
        before_snapshot = self._snapshot(valid_doc["id"])

        usage = get_schema_usage(
            self.db_path,
            schema_id=schema["id"],
            actor_id=self.editor["id"],
        )

        self.assertEqual(usage["schema_id"], schema["id"])
        self.assertEqual(usage["project_id"], self.project["id"])
        self.assertEqual(usage["schema"]["name"], "number-value")
        self.assertNotIn("schema", usage["schema"])
        self.assertEqual(usage["status"], "invalid")
        self.assertEqual(usage["summary"], {
            "bound_documents": 2,
            "valid_documents": 1,
            "invalid_documents": 1,
            "deleted_documents": 0,
        })
        self.assertEqual(usage["pagination"], {"limit": 50, "offset": 0, "total": 2, "has_more": False})
        by_id = {document["document_id"]: document for document in usage["documents"]}
        self.assertTrue(by_id[valid_doc["id"]]["validation"]["valid"])
        self.assertFalse(by_id[invalid_doc["id"]]["validation"]["valid"])
        self.assertEqual(by_id[invalid_doc["id"]]["validation"]["errors"][0]["path"], "/value")
        self.assertEqual(by_id[invalid_doc["id"]]["validation"]["errors"][0]["validator"], "minimum")
        self.assertNotIn("content", by_id[valid_doc["id"]])
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._audit_count(), before_audit)
        self.assertEqual(self._snapshot(valid_doc["id"]), before_snapshot)

    def test_usage_reports_malformed_snapshot_json_as_invalid_document(self) -> None:
        schema = self._number_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/malformed-schema-usage.json",
            schema_id=schema["id"],
            content={"value": 20},
        )
        before_events = self._event_count()
        before_audit = self._audit_count()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_snapshot_json = ?
                WHERE id = ?
                """,
                ('{"value":', document["id"]),
            )

        usage = get_schema_usage(
            self.db_path,
            schema_id=schema["id"],
            actor_id=self.editor["id"],
        )

        self.assertEqual(usage["status"], "invalid")
        self.assertEqual(usage["summary"], {
            "bound_documents": 1,
            "valid_documents": 0,
            "invalid_documents": 1,
            "deleted_documents": 0,
        })
        document_usage = usage["documents"][0]
        self.assertEqual(document_usage["document_id"], document["id"])
        self.assertFalse(document_usage["validation"]["valid"])
        self.assertEqual(document_usage["validation"]["errors"][0]["validator"], "json_syntax")
        self.assertEqual(document_usage["validation"]["errors"][0]["details"]["field"], "current_snapshot_json")
        self.assertNotIn("content", document_usage)
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._audit_count(), before_audit)

    def test_usage_reports_invalid_persisted_json_schema_as_invalid_document(self) -> None:
        schema = self._invalid_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/invalid-persisted-schema.json",
            content={"value": 20},
        )
        self._bind_schema_directly(document["id"], schema["id"])
        before_events = self._event_count()
        before_audit = self._audit_count()

        usage = get_schema_usage(
            self.db_path,
            schema_id=schema["id"],
            actor_id=self.editor["id"],
        )

        self.assertEqual(usage["status"], "invalid")
        self.assertEqual(usage["schema_json_error"]["diagnostic_code"], "SCHEMA_JSON_SCHEMA_INVALID")
        self.assertEqual(usage["summary"], {
            "bound_documents": 1,
            "valid_documents": 0,
            "invalid_documents": 1,
            "deleted_documents": 0,
        })
        document_usage = usage["documents"][0]
        self.assertEqual(document_usage["document_id"], document["id"])
        self.assertFalse(document_usage["validation"]["valid"])
        self.assertEqual(document_usage["validation"]["errors"][0]["validator"], "schema_json_invalid")
        self.assertEqual(
            document_usage["validation"]["errors"][0]["details"]["diagnostic_code"],
            "SCHEMA_JSON_SCHEMA_INVALID",
        )
        self.assertNotIn("content", document_usage)
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._audit_count(), before_audit)

    def test_only_invalid_include_deleted_and_pagination_policy(self) -> None:
        schema = self._number_schema()
        valid_a = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/valid-a.json",
            schema_id=schema["id"],
            content={"value": 20},
        )
        valid_b = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/valid-b.json",
            schema_id=schema["id"],
            content={"value": 30},
        )
        invalid_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/invalid.json",
            content={"value": 1},
        )
        self._bind_schema_directly(invalid_doc["id"], schema["id"])
        deleted_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/deleted.json",
            schema_id=schema["id"],
            content={"value": 40},
        )
        delete_document(
            self.db_path,
            document_id=deleted_doc["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )

        only_invalid = get_schema_usage(
            self.db_path,
            schema_id=schema["id"],
            actor_id=self.reviewer["id"],
            only_invalid=True,
        )
        default_usage = get_schema_usage(
            self.db_path,
            schema_id=schema["id"],
            actor_id=self.reviewer["id"],
        )
        with_deleted = get_schema_usage(
            self.db_path,
            schema_id=schema["id"],
            actor_id=self.reviewer["id"],
            include_deleted=True,
            limit=2,
            offset=1,
        )

        self.assertEqual(only_invalid["summary"]["bound_documents"], 3)
        self.assertEqual([document["document_id"] for document in only_invalid["documents"]], [invalid_doc["id"]])
        self.assertEqual(only_invalid["pagination"], {"limit": 50, "offset": 0, "total": 1, "has_more": False})
        self.assertEqual(
            {document["document_id"] for document in default_usage["documents"]},
            {valid_a["id"], valid_b["id"], invalid_doc["id"]},
        )
        self.assertNotIn(deleted_doc["id"], {document["document_id"] for document in default_usage["documents"]})
        self.assertEqual(with_deleted["summary"]["bound_documents"], 4)
        self.assertEqual(with_deleted["summary"]["deleted_documents"], 1)
        self.assertEqual(with_deleted["pagination"], {"limit": 2, "offset": 1, "total": 4, "has_more": True})
        self.assertEqual(len(with_deleted["documents"]), 2)

    def test_validation_and_permission_policy(self) -> None:
        schema = self._number_schema()
        for kwargs in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            with self.assertRaises(AppError) as raised:
                get_schema_usage(
                    self.db_path,
                    schema_id=schema["id"],
                    actor_id=self.owner["id"],
                    **kwargs,
                )
            self.assertEqual(raised.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(AppError) as missing_schema:
            get_schema_usage(
                self.db_path,
                schema_id="missing_schema",
                actor_id=self.owner["id"],
            )
        self.assertEqual(missing_schema.exception.code, ErrorCode.SCHEMA_NOT_FOUND)

        for actor in (self.owner, self.admin, self.editor, self.reviewer):
            usage = get_schema_usage(
                self.db_path,
                schema_id=schema["id"],
                actor_id=actor["id"],
            )
            self.assertEqual(usage["schema_id"], schema["id"])

        for actor in (self.viewer, self.nonmember):
            with self.assertRaises(AppError) as denied:
                get_schema_usage(
                    self.db_path,
                    schema_id=schema["id"],
                    actor_id=actor["id"],
                )
            self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as missing_actor:
            get_schema_usage(
                self.db_path,
                schema_id=schema["id"],
                actor_id=None,
            )
        self.assertEqual(missing_actor.exception.code, ErrorCode.AUTH_REQUIRED)

    def test_http_route_and_api_token_scope(self) -> None:
        schema = self._number_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/http.json",
            schema_id=schema["id"],
            content={"value": 20},
        )
        other_schema = create_schema(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            name="other",
            version="1",
            schema_json={"type": "object"},
        )
        client = TestClient(create_app(self.db_path))
        editor_token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.editor["id"]},
            json={"name": "editor schema usage token"},
        )
        viewer_token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.viewer["id"]},
            json={"name": "viewer schema usage token"},
        )
        self.assertEqual(editor_token_response.status_code, 200)
        self.assertEqual(viewer_token_response.status_code, 200)
        editor_token = editor_token_response.json()["token"]
        viewer_token = viewer_token_response.json()["token"]

        usage_response = client.get(
            f"/schemas/{schema['id']}/usage",
            headers={"Authorization": f"Bearer {editor_token}"},
        )
        other_schema_response = client.get(
            f"/schemas/{other_schema['id']}/usage",
            headers={"Authorization": f"Bearer {editor_token}"},
        )
        viewer_response = client.get(
            f"/schemas/{schema['id']}/usage",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )

        self.assertEqual(usage_response.status_code, 200)
        self.assertEqual(usage_response.json()["documents"][0]["document_id"], document["id"])
        self.assertNotIn("content", usage_response.json()["documents"][0])
        self.assertEqual(other_schema_response.status_code, 403)
        self.assertEqual(other_schema_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(viewer_response.status_code, 403)
        self.assertEqual(viewer_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

    def test_http_usage_reports_malformed_snapshot_json_without_server_error(self) -> None:
        schema = self._number_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/http-malformed-schema-usage.json",
            schema_id=schema["id"],
            content={"value": 20},
        )
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_snapshot_json = ?
                WHERE id = ?
                """,
                ('{"value":', document["id"]),
            )
        client = TestClient(create_app(self.db_path))

        response = client.get(
            f"/schemas/{schema['id']}/usage",
            headers={"X-Actor-Id": self.editor["id"]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "invalid")
        self.assertEqual(payload["summary"]["invalid_documents"], 1)
        document_usage = payload["documents"][0]
        self.assertEqual(document_usage["document_id"], document["id"])
        self.assertEqual(document_usage["validation"]["errors"][0]["validator"], "json_syntax")
        self.assertEqual(document_usage["validation"]["errors"][0]["details"]["field"], "current_snapshot_json")

    def test_schema_usage_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/schemas/{schema_id}/usage", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
