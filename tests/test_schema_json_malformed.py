from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db, utc_now
from app.document_service import (
    create_document,
    delete_document,
    patch_document,
    preview_document_patch,
    restore_document,
    rollback_document,
    validate_document,
)
from app.errors import AppError, ErrorCode
from app.export_service import export_project_archive
from app.main import create_app
from app.schema_service import get_schema, list_project_schemas
from app.schema_usage_service import get_schema_usage
from app.validation_report_service import get_project_validation_report
from app.workspace_service import create_project, create_user, create_workspace


class SchemaJsonMalformedTests(unittest.TestCase):
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

    def _insert_malformed_schema(self, *, schema_id: str = "schema_malformed", file_pattern: str | None = None) -> dict:
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
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    schema_id,
                    self.project["id"],
                    "malformed",
                    "1",
                    '{"type":',
                    file_pattern,
                    self.owner["id"],
                    now,
                ),
            )
        return {"id": schema_id, "project_id": self.project["id"]}

    def _insert_invalid_schema(self, *, schema_id: str = "schema_invalid_json_schema") -> dict:
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
                    schema_id,
                    self.project["id"],
                    "invalid-json-schema",
                    "1",
                    json.dumps({"type": 1}, separators=(",", ":")),
                    self.owner["id"],
                    now,
                ),
            )
        return {"id": schema_id, "project_id": self.project["id"]}

    def _bind_schema(self, document_id: str, schema_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET schema_id = ?
                WHERE id = ?
                """,
                (schema_id, document_id),
            )

    def _event_count(self, document_id: str | None = None) -> int:
        with connect(self.db_path) as conn:
            if document_id is None:
                return conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _document_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"]

    def _document_row(self, document_id: str) -> dict:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT current_version, current_snapshot_json, deleted_at
                FROM json_documents
                WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
        return {
            "current_version": row["current_version"],
            "content": json.loads(row["current_snapshot_json"]),
            "deleted_at": row["deleted_at"],
        }

    def _assert_schema_decode_error(self, error: AppError, schema_id: str) -> None:
        self.assertEqual(error.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(error.message, "Stored schema_json is malformed.")
        self.assertEqual(error.details["diagnostic_code"], "SCHEMA_JSON_DECODE_FAILED")
        self.assertEqual(error.details["schema_id"], schema_id)
        self.assertEqual(error.details["project_id"], self.project["id"])
        self.assertEqual(error.details["field"], "schema_json")
        self.assertEqual(error.details["message"], "Expecting value")

    def _assert_invalid_schema_error(self, error: AppError, schema_id: str) -> None:
        self.assertEqual(error.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(error.message, "Stored schema_json is not a valid JSON Schema.")
        self.assertEqual(error.details["diagnostic_code"], "SCHEMA_JSON_SCHEMA_INVALID")
        self.assertEqual(error.details["schema_id"], schema_id)
        self.assertEqual(error.details["project_id"], self.project["id"])
        self.assertEqual(error.details["field"], "schema_json")
        self.assertIn("is not valid", error.details["message"])

    def test_schema_get_list_and_http_report_malformed_schema_json_without_throwing(self) -> None:
        schema = self._insert_malformed_schema()
        client = TestClient(create_app(self.db_path))

        loaded = get_schema(self.db_path, schema["id"], actor_id=self.owner["id"])
        listed = list_project_schemas(self.db_path, self.project["id"], actor_id=self.owner["id"])
        response = client.get(
            f"/schemas/{schema['id']}",
            headers={"X-Actor-Id": self.owner["id"]},
        )

        self.assertIsNone(loaded["schema"])
        self.assertEqual(loaded["schema_json_error"]["diagnostic_code"], "SCHEMA_JSON_DECODE_FAILED")
        self.assertEqual(listed["schemas"][0]["schema_json_error"]["schema_id"], schema["id"])
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["schema"])
        self.assertEqual(response.json()["schema_json_error"]["field"], "schema_json")

    def test_schema_get_list_usage_and_validation_report_expose_invalid_json_schema_diagnostics(self) -> None:
        schema = self._insert_invalid_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/invalid-schema-diagnostic.json",
            content={"value": 1},
        )
        self._bind_schema(document["id"], schema["id"])
        client = TestClient(create_app(self.db_path))

        loaded = get_schema(self.db_path, schema["id"], actor_id=self.owner["id"])
        listed = list_project_schemas(self.db_path, self.project["id"], actor_id=self.owner["id"])
        usage = get_schema_usage(self.db_path, schema_id=schema["id"], actor_id=self.owner["id"])
        report = get_project_validation_report(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        response = client.get(
            f"/schemas/{schema['id']}/usage",
            headers={"X-Actor-Id": self.owner["id"]},
        )

        self.assertEqual(loaded["schema_json_error"]["diagnostic_code"], "SCHEMA_JSON_SCHEMA_INVALID")
        self.assertEqual(listed["schemas"][0]["schema_json_error"]["schema_id"], schema["id"])
        self.assertEqual(usage["schema_json_error"]["diagnostic_code"], "SCHEMA_JSON_SCHEMA_INVALID")
        self.assertEqual(usage["documents"][0]["validation"]["errors"][0]["validator"], "schema_json_invalid")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["documents"][0]["validation"]["errors"][0]["validator"], "schema_json_invalid")
        document_report = report["documents"][0]
        self.assertFalse(document_report["validation"]["valid"])
        self.assertEqual(document_report["validation"]["errors"][0]["validator"], "schema_json_invalid")

    def test_schema_bound_mutations_with_invalid_persisted_json_schema_fail_without_partial_write(self) -> None:
        schema = self._insert_invalid_schema()

        with self.assertRaises(AppError) as create_error:
            create_document(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                full_path="config/create-invalid-schema.json",
                schema_id=schema["id"],
                content={"value": 1},
            )
        self._assert_invalid_schema_error(create_error.exception, schema["id"])
        self.assertEqual(self._document_count(), 0)
        self.assertEqual(self._event_count(), 0)

        patch_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/patch-invalid-schema.json",
            content={"value": 1},
        )
        self._bind_schema(patch_doc["id"], schema["id"])
        before_patch_row = self._document_row(patch_doc["id"])
        before_patch_events = self._event_count(patch_doc["id"])
        with self.assertRaises(AppError) as patch_error:
            patch_document(
                self.db_path,
                document_id=patch_doc["id"],
                actor_id=self.owner["id"],
                base_version=1,
                patch=[{"op": "replace", "path": "/value", "value": 2}],
            )
        self._assert_invalid_schema_error(patch_error.exception, schema["id"])
        self.assertEqual(self._document_row(patch_doc["id"]), before_patch_row)
        self.assertEqual(self._event_count(patch_doc["id"]), before_patch_events)

        with self.assertRaises(AppError) as preview_error:
            preview_document_patch(
                self.db_path,
                document_id=patch_doc["id"],
                actor_id=self.owner["id"],
                base_version=1,
                patch=[{"op": "replace", "path": "/value", "value": 2}],
            )
        self._assert_invalid_schema_error(preview_error.exception, schema["id"])
        self.assertEqual(self._document_row(patch_doc["id"]), before_patch_row)
        self.assertEqual(self._event_count(patch_doc["id"]), before_patch_events)

        validate_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/validate-invalid-schema.json",
            content={"value": 1},
        )
        self._bind_schema(validate_doc["id"], schema["id"])
        before_validate_events = self._event_count(validate_doc["id"])
        with self.assertRaises(AppError) as validate_error:
            validate_document(self.db_path, validate_doc["id"], actor_id=self.owner["id"])
        self._assert_invalid_schema_error(validate_error.exception, schema["id"])
        self.assertEqual(self._event_count(validate_doc["id"]), before_validate_events)

        rollback_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/rollback-invalid-schema.json",
            content={"value": 1},
        )
        patch_document(
            self.db_path,
            document_id=rollback_doc["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
        )
        self._bind_schema(rollback_doc["id"], schema["id"])
        before_rollback_row = self._document_row(rollback_doc["id"])
        before_rollback_events = self._event_count(rollback_doc["id"])
        with self.assertRaises(AppError) as rollback_error:
            rollback_document(
                self.db_path,
                document_id=rollback_doc["id"],
                actor_id=self.owner["id"],
                base_version=2,
                target_version=1,
            )
        self._assert_invalid_schema_error(rollback_error.exception, schema["id"])
        self.assertEqual(self._document_row(rollback_doc["id"]), before_rollback_row)
        self.assertEqual(self._event_count(rollback_doc["id"]), before_rollback_events)

        restore_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/restore-invalid-schema.json",
            content={"value": 1},
        )
        self._bind_schema(restore_doc["id"], schema["id"])
        delete_document(
            self.db_path,
            document_id=restore_doc["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )
        before_restore_row = self._document_row(restore_doc["id"])
        before_restore_events = self._event_count(restore_doc["id"])
        with self.assertRaises(AppError) as restore_error:
            restore_document(
                self.db_path,
                document_id=restore_doc["id"],
                actor_id=self.owner["id"],
                base_version=2,
            )
        self._assert_invalid_schema_error(restore_error.exception, schema["id"])
        self.assertIsNotNone(before_restore_row["deleted_at"])
        self.assertEqual(self._document_row(restore_doc["id"]), before_restore_row)
        self.assertEqual(self._event_count(restore_doc["id"]), before_restore_events)

    def test_schema_bound_create_patch_rollback_and_validate_fail_without_partial_write(self) -> None:
        schema = self._insert_malformed_schema()

        with self.assertRaises(AppError) as create_error:
            create_document(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                full_path="config/create.json",
                schema_id=schema["id"],
                content={"value": 1},
            )
        self._assert_schema_decode_error(create_error.exception, schema["id"])
        self.assertEqual(self._document_count(), 0)
        self.assertEqual(self._event_count(), 0)

        patch_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/patch.json",
            content={"value": 1},
        )
        self._bind_schema(patch_doc["id"], schema["id"])
        before_patch_row = self._document_row(patch_doc["id"])
        before_patch_events = self._event_count(patch_doc["id"])
        with self.assertRaises(AppError) as patch_error:
            patch_document(
                self.db_path,
                document_id=patch_doc["id"],
                actor_id=self.owner["id"],
                base_version=1,
                patch=[{"op": "replace", "path": "/value", "value": 2}],
            )
        self._assert_schema_decode_error(patch_error.exception, schema["id"])
        self.assertEqual(self._document_row(patch_doc["id"]), before_patch_row)
        self.assertEqual(self._event_count(patch_doc["id"]), before_patch_events)

        validate_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/validate.json",
            content={"value": 1},
        )
        self._bind_schema(validate_doc["id"], schema["id"])
        with self.assertRaises(AppError) as validate_error:
            validate_document(self.db_path, validate_doc["id"], actor_id=self.owner["id"])
        self._assert_schema_decode_error(validate_error.exception, schema["id"])
        self.assertEqual(self._event_count(validate_doc["id"]), 1)

        rollback_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/rollback.json",
            content={"value": 1},
        )
        patch_document(
            self.db_path,
            document_id=rollback_doc["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
        )
        self._bind_schema(rollback_doc["id"], schema["id"])
        before_rollback_row = self._document_row(rollback_doc["id"])
        before_rollback_events = self._event_count(rollback_doc["id"])
        with self.assertRaises(AppError) as rollback_error:
            rollback_document(
                self.db_path,
                document_id=rollback_doc["id"],
                actor_id=self.owner["id"],
                base_version=2,
                target_version=1,
            )
        self._assert_schema_decode_error(rollback_error.exception, schema["id"])
        self.assertEqual(self._document_row(rollback_doc["id"]), before_rollback_row)
        self.assertEqual(self._event_count(rollback_doc["id"]), before_rollback_events)

    def test_schema_bound_restore_with_malformed_schema_json_fails_without_partial_write(self) -> None:
        schema = self._insert_malformed_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/restore.json",
            content={"value": 1},
        )
        self._bind_schema(document["id"], schema["id"])
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )
        before_restore_row = self._document_row(document["id"])
        before_restore_events = self._event_count(document["id"])

        with self.assertRaises(AppError) as restore_error:
            restore_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                base_version=2,
            )

        self._assert_schema_decode_error(restore_error.exception, schema["id"])
        self.assertIsNotNone(before_restore_row["deleted_at"])
        self.assertEqual(self._document_row(document["id"]), before_restore_row)
        self.assertEqual(self._event_count(document["id"]), before_restore_events)

    def test_usage_validation_report_and_export_expose_malformed_schema_json_diagnostics(self) -> None:
        schema = self._insert_malformed_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/report.json",
            content={"value": 1},
        )
        self._bind_schema(document["id"], schema["id"])

        usage = get_schema_usage(self.db_path, schema_id=schema["id"], actor_id=self.owner["id"])
        report = get_project_validation_report(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        archive = export_project_archive(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(usage["schema_json_error"]["diagnostic_code"], "SCHEMA_JSON_DECODE_FAILED")
        self.assertEqual(usage["documents"][0]["validation"]["errors"][0]["validator"], "schema_json_syntax")
        document_report = report["documents"][0]
        self.assertFalse(document_report["validation"]["valid"])
        self.assertEqual(document_report["validation"]["errors"][0]["validator"], "schema_json_syntax")
        self.assertIsNone(archive["schemas"][0]["schema"])
        self.assertEqual(archive["schemas"][0]["schema_json_error"]["schema_id"], schema["id"])


if __name__ == "__main__":
    unittest.main()
