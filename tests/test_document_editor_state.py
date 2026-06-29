from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db, utc_now
from app.document_service import (
    assert_replay_matches_latest,
    create_document,
    delete_document,
    get_document_editor_state,
    get_history,
    patch_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.schema_service import create_schema
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class DocumentEditorStateTests(unittest.TestCase):
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

    def _strict_schema(self) -> dict:
        return create_schema(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name="editor_state_config",
            version="1.0.0",
            schema_json={
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "number", "minimum": 1}},
                "additionalProperties": False,
            },
        )

    def _create_bound_document(self) -> tuple[dict, dict]:
        schema = self._strict_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/editor-state.json",
            schema_id=schema["id"],
            content={"value": 1},
        )
        return schema, document

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _document_version(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT current_version FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()["current_version"]

    def _insert_invalid_schema(self, schema_id: str = "schema_editor_state_invalid") -> dict:
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
                    "editor-state-invalid-schema",
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
                "UPDATE json_documents SET schema_id = ? WHERE id = ?",
                (schema_id, document_id),
            )

    def _client(self) -> TestClient:
        return TestClient(create_app(self.db_path))

    def _create_token(self, client: TestClient) -> dict:
        response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "editor state token"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_editor_state_returns_snapshot_schema_capabilities_validation_and_recent_events(self) -> None:
        schema, document = self._create_bound_document()
        patched = patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
            reason="prepare editor state",
        )
        before_events = self._event_count(document["id"])

        state = get_document_editor_state(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            include_validation=True,
            recent_events_limit=1,
        )

        self.assertEqual(state["document"]["id"], document["id"])
        self.assertEqual(state["document"]["content"], {"value": 2})
        self.assertEqual(json.loads(state["document"]["content_text"]), state["document"]["content"])
        self.assertEqual(state["document"]["content_text"], '{\n  "value": 2\n}')
        self.assertEqual(
            state["document"]["content_text_format"],
            {"encoding": "utf-8", "indent": 2, "sort_keys": True, "source": "current_snapshot_json"},
        )
        self.assertEqual(state["editor"]["actor_id"], self.owner["id"])
        self.assertEqual(state["editor"]["role"], "owner")
        self.assertTrue(state["editor"]["capabilities"]["can_patch"])
        self.assertTrue(state["editor"]["capabilities"]["can_patch_preview"])
        self.assertTrue(state["editor"]["capabilities"]["can_validate"])
        self.assertEqual(state["editor"]["required_base_version"], patched["current_version"])
        self.assertEqual(state["editor"]["supported_patch_operations"], ["add", "replace", "remove"])
        self.assertEqual(state["editor"]["conflict_policy"], "reject_stale_base_version")
        self.assertEqual(state["editor"]["persistence"], "validated_document_event")
        self.assertEqual(state["workflow"]["mode"], "non_realtime_versioned_edit")
        self.assertEqual(state["workflow"]["canonical_source"], "document.content")
        self.assertEqual(state["workflow"]["raw_text_source"], "document.content_text")
        self.assertEqual(state["workflow"]["base_version_field"], "base_version")
        self.assertEqual(state["workflow"]["required_base_version"], patched["current_version"])
        self.assertEqual(state["workflow"]["supported_content_sources"], ["content", "content_text"])
        self.assertEqual(state["workflow"]["save_contract"]["accepted_event_required"], True)
        self.assertEqual(state["workflow"]["save_contract"]["snapshot_update_requires_event"], True)
        self.assertEqual(state["workflow"]["save_contract"]["conflict_error_code"], ErrorCode.VERSION_CONFLICT)
        self.assertIn(
            "POST /documents/{document_id}/content-conflict-preview",
            state["workflow"]["save_contract"]["recovery"],
        )
        actions = state["workflow"]["actions"]
        self.assertEqual(actions["reload"]["endpoint"], f"/documents/{document['id']}/editor-state")
        self.assertTrue(actions["reload"]["available"])
        self.assertTrue(actions["preview_content_conflict"]["available"])
        self.assertTrue(actions["preview_content_conflict"]["read_only"])
        self.assertTrue(actions["preview_content_conflict"]["allows_stale_existing_base_version"])
        self.assertEqual(actions["save_content"]["endpoint"], f"/documents/{document['id']}/content")
        self.assertTrue(actions["save_content"]["creates_document_event"])
        self.assertEqual(actions["diff"]["query"], {"from_version": 1, "to_version": patched["current_version"]})
        state_machine = state["workflow"]["state_machine"]
        self.assertEqual(state_machine["version"], "task094.non_realtime_editor_state_machine.v1")
        self.assertEqual(state_machine["initial_state"], "clean")
        self.assertIn("dirty", state_machine["client_owned_states"])
        self.assertIn("stale_conflict", state_machine["server_verified_states"])
        self.assertIn("preview_content", state_machine["states"]["clean"]["allowed_actions"])
        self.assertIn("save_content", state_machine["states"]["preview_ready"]["allowed_actions"])
        self.assertTrue(state_machine["states"]["preview_ready"]["can_persist"])
        self.assertTrue(state_machine["states"]["saved"]["creates_document_event"])
        self.assertFalse(state_machine["states"]["stale_conflict"]["creates_document_event"])
        self.assertIn(
            {"from": "saving", "on": "version_conflict", "to": "stale_conflict"},
            state_machine["transitions"],
        )
        self.assertEqual(state_machine["event_creation"]["only_on"], ["save_success"])
        self.assertIn("version_conflict", state_machine["event_creation"]["never_on"])
        self.assertEqual(state["schema"]["id"], schema["id"])
        self.assertTrue(state["validation"]["available"])
        self.assertTrue(state["validation"]["valid"])
        self.assertEqual(state["validation"]["errors"], [])
        self.assertEqual(len(state["recent_events"]), 1)
        self.assertEqual(state["recent_events"][0]["event_type"], "update")
        self.assertEqual(state["recent_events"][0]["result_version"], 2)
        self.assertEqual(self._event_count(document["id"]), before_events)
        self.assertEqual(self._document_version(document["id"]), 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_viewer_editor_state_is_read_only_and_validation_unavailable(self) -> None:
        _, document = self._create_bound_document()
        before_events = self._event_count(document["id"])

        state = get_document_editor_state(
            self.db_path,
            document_id=document["id"],
            actor_id=self.viewer["id"],
            include_validation=True,
        )

        self.assertEqual(state["editor"]["role"], "viewer")
        self.assertTrue(state["editor"]["capabilities"]["can_read"])
        self.assertFalse(state["editor"]["capabilities"]["can_patch"])
        self.assertFalse(state["editor"]["capabilities"]["can_patch_preview"])
        self.assertFalse(state["editor"]["capabilities"]["can_validate"])
        self.assertFalse(state["editor"]["capabilities"]["can_comment"])
        self.assertFalse(state["workflow"]["actions"]["preview_content"]["available"])
        self.assertFalse(state["workflow"]["actions"]["preview_content_conflict"]["available"])
        self.assertFalse(state["workflow"]["actions"]["save_content"]["available"])
        self.assertFalse(state["workflow"]["actions"]["rollback"]["available"])
        self.assertTrue(state["workflow"]["actions"]["history"]["available"])
        self.assertEqual(state["workflow"]["state_machine"]["initial_state"], "read_only")
        self.assertFalse(state["workflow"]["state_machine"]["states"]["read_only"]["can_persist"])
        self.assertNotIn("preview_content", state["workflow"]["state_machine"]["states"]["read_only"]["allowed_actions"])
        self.assertNotIn("save_content", state["workflow"]["state_machine"]["states"]["preview_ready"]["allowed_actions"])
        self.assertFalse(state["workflow"]["state_machine"]["states"]["preview_ready"]["can_persist"])
        self.assertEqual(state["validation"], {"available": False, "reason": "permission_denied"})
        self.assertEqual(self._event_count(document["id"]), before_events)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_editor_state_validation_can_be_omitted_without_mutation(self) -> None:
        _, document = self._create_bound_document()

        state = get_document_editor_state(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            include_validation=False,
            recent_events_limit=0,
        )

        self.assertEqual(state["validation"], {"available": False, "reason": "not_requested"})
        self.assertEqual(state["recent_events"], [])
        self.assertEqual(self._event_count(document["id"]), 1)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_editor_state_rejects_soft_deleted_document_but_keeps_history(self) -> None:
        _, document = self._create_bound_document()
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )

        with self.assertRaises(AppError) as raised:
            get_document_editor_state(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
            )

        self.assertEqual(raised.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)
        history = get_history(self.db_path, document["id"], actor_id=self.owner["id"])
        self.assertEqual([event["event_type"] for event in history["events"]], ["create", "delete"])
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_editor_state_surfaces_invalid_bound_schema_as_read_only_diagnostic(self) -> None:
        schema = self._insert_invalid_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/editor-invalid-schema.json",
            content={"value": 1},
        )
        self._bind_schema(document["id"], schema["id"])
        before_events = self._event_count(document["id"])

        state = get_document_editor_state(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            include_validation=True,
        )

        self.assertEqual(state["schema"]["schema_json_error"]["diagnostic_code"], "SCHEMA_JSON_SCHEMA_INVALID")
        self.assertEqual(state["validation"]["available"], False)
        self.assertEqual(state["validation"]["reason"], "schema_unavailable")
        self.assertEqual(state["validation"]["error"]["code"], ErrorCode.INTERNAL_ERROR)
        self.assertEqual(
            state["validation"]["error"]["details"]["diagnostic_code"],
            "SCHEMA_JSON_SCHEMA_INVALID",
        )
        self.assertEqual(self._event_count(document["id"]), before_events)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_http_editor_state_supports_bearer_token_scope_and_route_registration(self) -> None:
        _, document = self._create_bound_document()
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other-editor-state.json",
            content={"value": 1},
        )
        client = self._client()
        token = self._create_token(client)
        headers = {"Authorization": f"Bearer {token['token']}"}

        response = client.get(
            f"/documents/{document['id']}/editor-state",
            headers=headers,
            params={"recent_events_limit": 1},
        )
        denied = client.get(f"/documents/{other_document['id']}/editor-state", headers=headers)
        bad_limit = client.get(
            f"/documents/{document['id']}/editor-state",
            headers=headers,
            params={"recent_events_limit": 51},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["document"]["id"], document["id"])
        self.assertEqual(json.loads(response.json()["document"]["content_text"]), response.json()["document"]["content"])
        self.assertEqual(response.json()["document"]["content_text_format"]["source"], "current_snapshot_json")
        self.assertEqual(response.json()["editor"]["role"], "owner")
        self.assertEqual(response.json()["workflow"]["actions"]["save_patch"]["method"], "PATCH")
        self.assertTrue(response.json()["workflow"]["actions"]["save_patch"]["creates_document_event"])
        self.assertEqual(response.json()["workflow"]["state_machine"]["initial_state"], "clean")
        self.assertIn("save_success", response.json()["workflow"]["state_machine"]["event_creation"]["only_on"])
        self.assertTrue(response.json()["validation"]["available"])
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(bad_limit.status_code, 400)
        self.assertEqual(bad_limit.json()["error"]["code"], ErrorCode.INVALID_REQUEST)

        routes = {(route.path, ",".join(sorted(route.methods))) for route in create_app(self.db_path).routes if hasattr(route, "methods")}
        self.assertIn(("/documents/{document_id}/editor-state", "GET"), routes)
        assert_replay_matches_latest(self.db_path, document["id"])
        assert_replay_matches_latest(self.db_path, other_document["id"])


if __name__ == "__main__":
    unittest.main()
