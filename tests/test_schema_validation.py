from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.database import connect, init_db, utc_now
from app.document_service import (
    assert_replay_matches_latest,
    create_document,
    delete_document,
    get_document,
    get_history,
    patch_document,
    preview_document_patch,
    restore_document,
    rollback_document,
    validate_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.schema_service import create_schema, get_schema, list_project_schemas


class SchemaValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.actor_id = "user_001"
        self.workspace_id = "workspace_001"
        self.project_id = "project_001"
        self.other_project_id = "project_002"
        now = utc_now()
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (self.actor_id, "user@example.com", "Test User", now, now),
            )
            conn.execute(
                "INSERT INTO workspaces (id, name, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (self.workspace_id, "Workspace", self.actor_id, now, now),
            )
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (self.project_id, self.workspace_id, "Project", None, now, now),
            )
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (self.other_project_id, self.workspace_id, "Other Project", None, now, now),
            )
            conn.execute(
                "INSERT INTO project_members (id, project_id, user_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
                ("member_001", self.project_id, self.actor_id, "owner", now),
            )
            conn.execute(
                "INSERT INTO project_members (id, project_id, user_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
                ("member_002", self.other_project_id, self.actor_id, "owner", now),
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _model_schema(self, *, minimum: float = 0.0, file_pattern: str | None = None) -> dict:
        return create_schema(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            name=f"model_config_{minimum}_{file_pattern or 'none'}",
            version="1.0.0",
            file_pattern=file_pattern,
            schema_json={
                "type": "object",
                "required": ["model", "learning_rate"],
                "properties": {
                    "model": {"type": "string"},
                    "learning_rate": {"type": "number", "minimum": minimum, "maximum": 1},
                },
                "additionalProperties": False,
            },
        )

    def _inactive_model_schema(self, *, schema_id: str = "schema_inactive") -> dict:
        schema_json = {
            "type": "object",
            "required": ["model", "learning_rate"],
            "properties": {
                "model": {"type": "string"},
                "learning_rate": {"type": "number"},
            },
            "additionalProperties": False,
        }
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
                VALUES (?, ?, ?, ?, ?, NULL, 0, ?, ?)
                """,
                (
                    schema_id,
                    self.project_id,
                    f"inactive_{schema_id}",
                    "1.0.0",
                    json.dumps(schema_json, sort_keys=True, separators=(",", ":")),
                    self.actor_id,
                    utc_now(),
                ),
            )
        return {"id": schema_id, "schema": schema_json}

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _table_count(self, table_name: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()["count"]

    def _document_row(self, document_id: str):
        with connect(self.db_path) as conn:
            return conn.execute("SELECT * FROM json_documents WHERE id = ?", (document_id,)).fetchone()

    def test_valid_schema_create_list_get(self) -> None:
        schema = self._model_schema(file_pattern="config/*.json")

        self.assertEqual(schema["project_id"], self.project_id)
        self.assertEqual(schema["version"], "1.0.0")
        self.assertTrue(schema["is_active"])

        listed = list_project_schemas(self.db_path, self.project_id, actor_id=self.actor_id)
        self.assertEqual([item["id"] for item in listed["schemas"]], [schema["id"]])

        loaded = get_schema(self.db_path, schema["id"], actor_id=self.actor_id)
        self.assertEqual(loaded["schema"]["required"], ["model", "learning_rate"])

    def test_schemas_table_is_immutable_at_db_level(self) -> None:
        schema = self._model_schema(file_pattern="config/*.json")

        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE schemas SET name = ? WHERE id = ?", ("changed", schema["id"]))
        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM schemas WHERE id = ?", (schema["id"],))

        listed = list_project_schemas(self.db_path, self.project_id, actor_id=self.actor_id)
        self.assertEqual(listed["schemas"][0]["id"], schema["id"])
        self.assertEqual(get_schema(self.db_path, schema["id"], actor_id=self.actor_id)["name"], schema["name"])

    def test_invalid_json_schema_rejected(self) -> None:
        with self.assertRaises(AppError) as raised:
            create_schema(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                name="invalid",
                version="1.0.0",
                schema_json={"type": 123},
            )

        self.assertEqual(raised.exception.code, ErrorCode.INVALID_JSON_SCHEMA)

    def test_schema_create_rejects_missing_project_and_actor(self) -> None:
        with self.assertRaises(AppError) as missing_project:
            create_schema(
                self.db_path,
                project_id="missing_project",
                actor_id=self.actor_id,
                name="missing_project",
                version="1.0.0",
                schema_json={"type": "object"},
            )
        self.assertEqual(missing_project.exception.code, ErrorCode.PROJECT_NOT_FOUND)

        with self.assertRaises(AppError) as missing_actor:
            create_schema(
                self.db_path,
                project_id=self.project_id,
                actor_id="missing_user",
                name="missing_actor",
                version="1.0.0",
                schema_json={"type": "object"},
            )
        self.assertEqual(missing_actor.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_document_create_with_explicit_schema_success(self) -> None:
        schema = self._model_schema(minimum=0.01)

        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/model.json",
            schema_id=schema["id"],
            content={"model": "baseline", "learning_rate": 0.1},
        )

        self.assertEqual(document["schema_id"], schema["id"])
        self.assertTrue(document["validation"]["valid"])
        self.assertEqual(get_document(self.db_path, document["id"], actor_id=self.actor_id)["schema_id"], schema["id"])
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_document_create_with_schema_invalid_content_rejects_without_document_or_event(self) -> None:
        schema = self._model_schema(minimum=0.01)

        with self.assertRaises(AppError) as raised:
            create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                full_path="config/invalid.json",
                schema_id=schema["id"],
                content={"model": "baseline", "learning_rate": 0.001},
            )

        self.assertEqual(raised.exception.code, ErrorCode.SCHEMA_VALIDATION_FAILED)
        with connect(self.db_path) as conn:
            documents = conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"]
            events = conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]
        self.assertEqual(documents, 0)
        self.assertEqual(events, 0)

    def test_schema_project_mismatch_rejected(self) -> None:
        schema = create_schema(
            self.db_path,
            project_id=self.other_project_id,
            actor_id=self.actor_id,
            name="other",
            version="1.0.0",
            schema_json={"type": "object"},
        )

        with self.assertRaises(AppError) as raised:
            create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                full_path="config/model.json",
                schema_id=schema["id"],
                content={"model": "baseline", "learning_rate": 0.1},
            )

        self.assertEqual(raised.exception.code, ErrorCode.SCHEMA_PROJECT_MISMATCH)

    def test_document_create_with_inactive_explicit_schema_rejected_without_document_or_event(self) -> None:
        schema = self._inactive_model_schema()
        before_documents = self._table_count("json_documents")
        before_events = self._table_count("document_events")

        with self.assertRaises(AppError) as raised:
            create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                full_path="config/inactive.json",
                schema_id=schema["id"],
                content={"model": "baseline", "learning_rate": 0.1},
            )

        self.assertEqual(raised.exception.code, ErrorCode.SCHEMA_NOT_ACTIVE)
        self.assertEqual(raised.exception.details, {"schema_id": schema["id"]})
        self.assertEqual(self._table_count("json_documents"), before_documents)
        self.assertEqual(self._table_count("document_events"), before_events)

    def test_file_pattern_auto_binding_success_no_match_and_multiple_match(self) -> None:
        schema = self._model_schema(file_pattern="config/*.json")
        bound = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/model.json",
            content={"model": "baseline", "learning_rate": 0.1},
        )
        self.assertEqual(bound["schema_id"], schema["id"])
        self.assertEqual(get_document(self.db_path, bound["id"], actor_id=self.actor_id)["schema_id"], schema["id"])

        unbound = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="notes/readme.json",
            content={"anything": True},
        )
        self.assertIsNone(unbound["schema_id"])
        self.assertIsNone(get_document(self.db_path, unbound["id"], actor_id=self.actor_id)["schema_id"])

        case_mismatch = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="CONFIG/model.json",
            content={"anything": True},
        )
        self.assertIsNone(case_mismatch["schema_id"])
        self.assertIsNone(get_document(self.db_path, case_mismatch["id"], actor_id=self.actor_id)["schema_id"])
        assert_replay_matches_latest(self.db_path, case_mismatch["id"])

        create_schema(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            name="specific_model",
            version="1.0.0",
            file_pattern="config/model.json",
            schema_json={"type": "object"},
        )
        with self.assertRaises(AppError) as raised:
            create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                full_path="config/model.json",
                content={"model": "baseline", "learning_rate": 0.1},
            )
        self.assertEqual(raised.exception.code, ErrorCode.AMBIGUOUS_SCHEMA_MATCH)

    def test_file_pattern_nested_match_policy_and_invalid_pattern_rejection(self) -> None:
        schema = self._model_schema(file_pattern="config/*.json")

        nested = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/nested/model.json",
            content={"model": "baseline", "learning_rate": 0.1},
        )
        self.assertEqual(nested["schema_id"], schema["id"])

        with self.assertRaises(AppError) as bad_path:
            create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                full_path="config\\model.json",
                content={"model": "baseline", "learning_rate": 0.1},
            )
        self.assertEqual(bad_path.exception.code, ErrorCode.PATCH_APPLY_FAILED)

        valid_deep = create_schema(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            name="deep_pattern",
            version="1.0.0",
            file_pattern="datasets/**/*.json",
            schema_json={"type": "object"},
        )
        self.assertEqual(valid_deep["file_pattern"], "datasets/**/*.json")

        invalid_patterns = (
            "",
            "   ",
            " config/*.json",
            "config/*.json ",
            "config\\*.json",
            "/config/*.json",
            "config/",
            "config//*.json",
            "config/./*.json",
            "config/../*.json",
        )
        before_schemas = self._table_count("schemas")
        before_documents = self._table_count("json_documents")
        before_events = self._table_count("document_events")
        for index, file_pattern in enumerate(invalid_patterns):
            with self.assertRaises(AppError) as bad_pattern:
                create_schema(
                    self.db_path,
                    project_id=self.project_id,
                    actor_id=self.actor_id,
                    name=f"bad_pattern_{index}",
                    version="1.0.0",
                    file_pattern=file_pattern,
                    schema_json={"type": "object"},
                )
            self.assertEqual(bad_pattern.exception.code, ErrorCode.INVALID_JSON_SCHEMA)
            self.assertEqual(self._table_count("schemas"), before_schemas)
            self.assertEqual(self._table_count("json_documents"), before_documents)
            self.assertEqual(self._table_count("document_events"), before_events)

    def test_http_invalid_file_pattern_rejected_without_mutation(self) -> None:
        client = TestClient(create_app(self.db_path))
        before_schemas = self._table_count("schemas")
        before_documents = self._table_count("json_documents")
        before_events = self._table_count("document_events")

        response = client.post(
            f"/projects/{self.project_id}/schemas",
            headers={"X-Actor-Id": self.actor_id},
            json={
                "name": "bad_http_pattern",
                "version": "1.0.0",
                "file_pattern": "config//*.json",
                "schema": {"type": "object"},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.INVALID_JSON_SCHEMA)
        self.assertEqual(self._table_count("schemas"), before_schemas)
        self.assertEqual(self._table_count("json_documents"), before_documents)
        self.assertEqual(self._table_count("document_events"), before_events)

    def test_http_inactive_explicit_schema_rejected_without_mutation(self) -> None:
        schema = self._inactive_model_schema(schema_id="schema_inactive_http")
        client = TestClient(create_app(self.db_path))
        before_documents = self._table_count("json_documents")
        before_events = self._table_count("document_events")

        response = client.post(
            f"/projects/{self.project_id}/documents",
            headers={"X-Actor-Id": self.actor_id},
            json={
                "full_path": "config/inactive-http.json",
                "schema_id": schema["id"],
                "content": {"model": "baseline", "learning_rate": 0.1},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.SCHEMA_NOT_ACTIVE)
        self.assertEqual(response.json()["error"]["details"], {"schema_id": schema["id"]})
        self.assertEqual(self._table_count("json_documents"), before_documents)
        self.assertEqual(self._table_count("document_events"), before_events)

    def test_schema_invalid_patch_rejects_without_event_version_or_snapshot_change(self) -> None:
        schema = self._model_schema(minimum=0.01)
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/model.json",
            schema_id=schema["id"],
            content={"model": "baseline", "learning_rate": 0.1},
        )

        with self.assertRaises(AppError) as raised:
            patch_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[{"op": "replace", "path": "/learning_rate", "value": 0.001}],
            )

        self.assertEqual(raised.exception.code, ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(self._event_count(document["id"]), 1)
        loaded = get_document(self.db_path, document["id"], actor_id=self.actor_id)
        self.assertEqual(loaded["current_version"], 1)
        self.assertEqual(loaded["content"]["learning_rate"], 0.1)

    def test_schema_invalid_patch_preview_rejects_without_event_or_snapshot_change(self) -> None:
        schema = self._model_schema(minimum=0.01)
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/preview-invalid.json",
            schema_id=schema["id"],
            content={"model": "baseline", "learning_rate": 0.1},
        )

        with self.assertRaises(AppError) as raised:
            preview_document_patch(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[{"op": "replace", "path": "/learning_rate", "value": 0.001}],
            )

        self.assertEqual(raised.exception.code, ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(self._event_count(document["id"]), 1)
        loaded = get_document(self.db_path, document["id"], actor_id=self.actor_id)
        self.assertEqual(loaded["current_version"], 1)
        self.assertEqual(loaded["content"], document["content"])

    def test_schema_valid_patch_succeeds(self) -> None:
        schema = self._model_schema(minimum=0.01)
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/model.json",
            schema_id=schema["id"],
            content={"model": "baseline", "learning_rate": 0.1},
        )

        patched = patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.2}],
        )

        self.assertEqual(patched["current_version"], 2)
        self.assertEqual(patched["schema_id"], schema["id"])
        self.assertTrue(patched["validation"]["valid"])
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_existing_inactive_schema_binding_still_validates_document_mutations(self) -> None:
        schema = self._inactive_model_schema(schema_id="schema_inactive_bound")
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/inactive-bound.json",
            content={"model": "baseline", "learning_rate": 0.1},
        )
        with connect(self.db_path) as conn:
            conn.execute("UPDATE json_documents SET schema_id = ? WHERE id = ?", (schema["id"], document["id"]))

        validation = validate_document(self.db_path, document["id"], actor_id=self.actor_id)
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["schema_id"], schema["id"])

        with self.assertRaises(AppError) as invalid_patch:
            patch_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[{"op": "remove", "path": "/learning_rate"}],
            )
        self.assertEqual(invalid_patch.exception.code, ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(self._event_count(document["id"]), 1)

        patched = patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.2}],
        )
        self.assertTrue(patched["validation"]["valid"])
        self.assertEqual(patched["schema_id"], schema["id"])

        rolled_back = rollback_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=2,
            target_version=1,
        )
        self.assertTrue(rolled_back["validation"]["valid"])
        self.assertEqual(rolled_back["schema_id"], schema["id"])

        deleted = delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=3,
        )
        self.assertIsNotNone(deleted["deleted_at"])
        restored = restore_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=4,
        )
        self.assertIsNone(restored["deleted_at"])
        self.assertTrue(restored["validation"]["valid"])
        self.assertEqual(restored["schema_id"], schema["id"])

        history = get_history(self.db_path, document["id"], actor_id=self.actor_id)["events"]
        self.assertEqual([event["event_type"] for event in history], ["create", "update", "rollback", "delete", "restore"])
        self.assertEqual(history[1]["validation_schema_id"], schema["id"])
        self.assertEqual(history[2]["validation_schema_id"], schema["id"])
        self.assertEqual(history[4]["validation_schema_id"], schema["id"])
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_schema_invalid_rollback_rejects_without_event_or_snapshot_change(self) -> None:
        schema = self._model_schema(minimum=0.01)
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/legacy.json",
            content={"model": "baseline", "learning_rate": 0.001},
        )
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.1}],
        )
        with connect(self.db_path) as conn:
            conn.execute("UPDATE json_documents SET schema_id = ? WHERE id = ?", (schema["id"], document["id"]))

        with self.assertRaises(AppError) as raised:
            rollback_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=2,
                target_version=1,
            )

        self.assertEqual(raised.exception.code, ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(self._event_count(document["id"]), 2)
        loaded = get_document(self.db_path, document["id"], actor_id=self.actor_id)
        self.assertEqual(loaded["current_version"], 2)
        self.assertEqual(loaded["content"]["learning_rate"], 0.1)

    def test_schema_valid_rollback_succeeds(self) -> None:
        schema = self._model_schema(minimum=0.01)
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/model.json",
            schema_id=schema["id"],
            content={"model": "baseline", "learning_rate": 0.1},
        )
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.2}],
        )

        rolled_back = rollback_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=2,
            target_version=1,
        )

        self.assertEqual(rolled_back["current_version"], 3)
        self.assertEqual(rolled_back["schema_id"], schema["id"])
        self.assertTrue(rolled_back["validation"]["valid"])
        self.assertEqual(
            get_history(self.db_path, document["id"], actor_id=self.actor_id)["events"][-1]["event_type"],
            "rollback",
        )
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_document_events_record_validation_schema_id(self) -> None:
        schema = self._model_schema(minimum=0.01)
        bound = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/model.json",
            schema_id=schema["id"],
            content={"model": "baseline", "learning_rate": 0.1},
        )
        patch_document(
            self.db_path,
            document_id=bound["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.2}],
        )
        rollback_document(
            self.db_path,
            document_id=bound["id"],
            actor_id=self.actor_id,
            base_version=2,
            target_version=1,
        )
        events = get_history(self.db_path, bound["id"], actor_id=self.actor_id)["events"]
        self.assertEqual([event["validation_schema_id"] for event in events], [schema["id"], schema["id"], schema["id"]])

        unbound = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="misc/unbound.json",
            content={"free": True},
        )
        self.assertIsNone(
            get_history(self.db_path, unbound["id"], actor_id=self.actor_id)["events"][0]["validation_schema_id"]
        )

        with self.assertRaises(AppError):
            patch_document(
                self.db_path,
                document_id=bound["id"],
                actor_id=self.actor_id,
                base_version=3,
                patch=[{"op": "replace", "path": "/learning_rate", "value": 0.001}],
            )
        self.assertEqual(len(get_history(self.db_path, bound["id"], actor_id=self.actor_id)["events"]), 3)

    def test_validate_document_bound_valid_invalid_and_unbound(self) -> None:
        schema = self._model_schema(minimum=0.01)
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/model.json",
            schema_id=schema["id"],
            content={"model": "baseline", "learning_rate": 0.1},
        )
        valid = validate_document(self.db_path, document["id"], actor_id=self.actor_id)
        self.assertTrue(valid["valid"])
        self.assertEqual(valid["document_id"], document["id"])
        self.assertEqual(valid["project_id"], self.project_id)
        self.assertEqual(valid["full_path"], "config/model.json")
        self.assertEqual(valid["current_version"], 1)
        self.assertIsNone(valid["deleted_at"])
        self.assertEqual(valid["schema_id"], schema["id"])

        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE json_documents SET current_snapshot_json = ? WHERE id = ?",
                (json.dumps({"model": "baseline", "learning_rate": 0.001}), document["id"]),
            )
        invalid = validate_document(self.db_path, document["id"], actor_id=self.actor_id)
        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["document_id"], document["id"])
        self.assertEqual(invalid["project_id"], self.project_id)
        self.assertEqual(invalid["full_path"], "config/model.json")
        self.assertEqual(invalid["current_version"], 1)
        self.assertEqual(invalid["errors"][0]["path"], "/learning_rate")

        unbound = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="misc/free.json",
            content={"free": True},
        )
        unbound_result = validate_document(self.db_path, unbound["id"], actor_id=self.actor_id)
        self.assertTrue(unbound_result["valid"])
        self.assertEqual(unbound_result["document_id"], unbound["id"])
        self.assertEqual(unbound_result["project_id"], self.project_id)
        self.assertEqual(unbound_result["full_path"], "misc/free.json")
        self.assertEqual(unbound_result["current_version"], 1)
        self.assertEqual(unbound_result["schema_id"], None)
        self.assertEqual(unbound_result["warnings"][0]["path"], "")

    def test_schema_error_paths_are_json_pointers_with_escaping(self) -> None:
        schema = create_schema(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            name="escaped",
            version="1.0.0",
            schema_json={
                "type": "object",
                "properties": {
                    "a/b": {"type": "number", "minimum": 10},
                    "c~d": {"type": "number", "maximum": 5},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"enum": ["ok"]}},
                        },
                    },
                },
            },
        )

        with self.assertRaises(AppError) as raised:
            create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                full_path="config/escaped.json",
                schema_id=schema["id"],
                content={"a/b": 1, "c~d": 9, "items": [{"name": "bad"}]},
            )

        self.assertEqual(raised.exception.code, ErrorCode.SCHEMA_VALIDATION_FAILED)
        errors = {error["path"]: error for error in raised.exception.details["errors"]}
        self.assertIn("/a~1b", errors)
        self.assertIn("/c~0d", errors)
        self.assertIn("/items/0/name", errors)

    def test_schema_routes_are_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/schemas", "POST"), routes)
        self.assertIn(("/projects/{project_id}/schemas", "GET"), routes)
        self.assertIn(("/schemas/{schema_id}", "GET"), routes)
        self.assertIn(("/documents/{document_id}/validate", "POST"), routes)

    def test_schema_endpoint_validation_error_shape(self) -> None:
        app = create_app(self.db_path)
        validation_handler = app.exception_handlers[RequestValidationError]
        validation_response = asyncio.run(
            validation_handler(
                None,
                RequestValidationError(
                    [{"type": "missing", "loc": ("body", "schema"), "msg": "Field required", "input": {}}]
                ),
            )
        )
        payload = json.loads(validation_response.body)
        self.assertEqual(set(payload.keys()), {"error"})
        self.assertEqual(payload["error"]["code"], ErrorCode.INVALID_JSON_SYNTAX)
        self.assertIn("details", payload["error"])

    def test_task001_database_migrates_to_task002_idempotently(self) -> None:
        old_db = str(Path(self.tmp.name) / "task001.sqlite3")
        now = utc_now()
        with connect(old_db) as conn:
            conn.executescript(
                """
                CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE projects (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE json_documents (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    full_path TEXT NOT NULL,
                    current_version INTEGER NOT NULL,
                    current_snapshot_json TEXT NOT NULL,
                    created_by TEXT NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE TABLE document_events (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES json_documents(id),
                    actor_id TEXT NOT NULL REFERENCES users(id),
                    event_type TEXT NOT NULL,
                    base_version INTEGER NOT NULL,
                    result_version INTEGER NOT NULL,
                    patch TEXT NOT NULL,
                    inverse_patch TEXT NOT NULL,
                    changed_paths TEXT NOT NULL,
                    before_values TEXT NOT NULL,
                    after_values TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(document_id, result_version)
                );
                """
            )
            conn.execute(
                "INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("user_old", "old@example.com", "Old User", now, now),
            )
            conn.execute(
                "INSERT INTO workspaces (id, name, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("workspace_old", "Old Workspace", "user_old", now, now),
            )
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("project_old", "workspace_old", "Old Project", None, now, now),
            )
            snapshot = {"model": "baseline", "learning_rate": 0.1}
            conn.execute(
                """
                INSERT INTO json_documents (
                    id, project_id, full_path, current_version, current_snapshot_json,
                    created_by, created_at, updated_at, deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                ("doc_old", "project_old", "config/model.json", 1, json.dumps(snapshot), "user_old", now, now),
            )
            conn.execute(
                """
                INSERT INTO document_events (
                    id, document_id, actor_id, event_type, base_version, result_version,
                    patch, inverse_patch, changed_paths, before_values, after_values,
                    summary, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "evt_old",
                    "doc_old",
                    "user_old",
                    "create",
                    0,
                    1,
                    json.dumps([{"op": "add", "path": "", "value": snapshot}]),
                    json.dumps([{"op": "remove", "path": ""}]),
                    json.dumps([""]),
                    json.dumps([{"path": "", "exists": False, "value": None}]),
                    json.dumps([{"path": "", "exists": True, "value": snapshot}]),
                    "Created config/model.json",
                    None,
                    now,
                ),
            )

        init_db(old_db)
        init_db(old_db)
        with connect(old_db) as conn:
            document_columns = {row["name"] for row in conn.execute("PRAGMA table_info(json_documents)").fetchall()}
            event_columns = {row["name"] for row in conn.execute("PRAGMA table_info(document_events)").fetchall()}
            schema_triggers = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'schemas'"
                ).fetchall()
            }
            comment_triggers = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'comments'"
                ).fetchall()
            }
            review_decision_triggers = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'review_decisions'"
                ).fetchall()
            }
            review_change_triggers = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'review_request_changes'"
                ).fetchall()
            }
            project_member_triggers = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'project_members'"
                ).fetchall()
            }
            event_foreign_keys = {
                (row["from"], row["table"], row["to"])
                for row in conn.execute("PRAGMA foreign_key_list(document_events)").fetchall()
            }
            document_foreign_keys = {
                (row["from"], row["table"], row["to"])
                for row in conn.execute("PRAGMA foreign_key_list(json_documents)").fetchall()
            }
            self.assertIn("schema_id", document_columns)
            self.assertIn("validation_schema_id", event_columns)
            self.assertIn("trg_schemas_no_update", schema_triggers)
            self.assertIn("trg_schemas_no_delete", schema_triggers)
            self.assertIn(("validation_schema_id", "schemas", "id"), event_foreign_keys)
            self.assertIn(("schema_id", "schemas", "id"), document_foreign_keys)
            self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schemas'").fetchone())
            self.assertIsNotNone(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='project_members'").fetchone()
            )
            self.assertIsNotNone(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='comment_threads'").fetchone()
            )
            self.assertIsNotNone(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='comments'").fetchone()
            )
            self.assertIsNotNone(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_requests'").fetchone()
            )
            self.assertIsNotNone(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_request_changes'").fetchone()
            )
            self.assertIsNotNone(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_decisions'").fetchone()
            )
            self.assertIn("trg_comments_no_update", comment_triggers)
            self.assertIn("trg_comments_no_delete", comment_triggers)
            self.assertIn("trg_review_decisions_no_update", review_decision_triggers)
            self.assertIn("trg_review_decisions_no_delete", review_decision_triggers)
            self.assertIn("trg_review_request_changes_no_update", review_change_triggers)
            self.assertIn("trg_review_request_changes_no_delete", review_change_triggers)
            self.assertIn("trg_project_members_keep_owner_update", project_member_triggers)
            self.assertIn("trg_project_members_keep_owner_delete", project_member_triggers)
            owner_member = conn.execute(
                """
                SELECT role
                FROM project_members
                WHERE project_id = ? AND user_id = ?
                """,
                ("project_old", "user_old"),
            ).fetchone()
            self.assertEqual(owner_member["role"], "owner")
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"], 1)
        schema = create_schema(
            old_db,
            project_id="project_old",
            actor_id="user_old",
            name="migrated",
            version="1.0.0",
            schema_json={"type": "object"},
        )
        with connect(old_db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE schemas SET name = ? WHERE id = ?", ("changed", schema["id"]))
        with connect(old_db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM schemas WHERE id = ?", (schema["id"],))
        assert_replay_matches_latest(old_db, "doc_old")


if __name__ == "__main__":
    unittest.main()
