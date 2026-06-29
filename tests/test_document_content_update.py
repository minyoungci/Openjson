from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db, utc_now
from app.document_service import (
    assert_replay_matches_latest,
    create_document,
    get_history,
    preview_document_content_conflict,
    preview_document_content_update,
    update_document_content,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.schema_service import create_schema


class DocumentContentUpdateTests(unittest.TestCase):
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

    def _client(self) -> TestClient:
        return TestClient(create_app(self.db_path))

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

    def _document_snapshot_json(self, document_id: str) -> str:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()["current_snapshot_json"]

    def _create_document(self) -> dict:
        return create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/raw-editor.json",
            content={
                "model": "baseline",
                "learning_rate": 0.001,
                "obsolete": True,
                "nested": {"keep": 1},
                "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            },
        )

    def _model_schema(self) -> dict:
        return create_schema(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            name="model_config",
            version="1.0.0",
            schema_json={
                "type": "object",
                "required": ["model", "learning_rate"],
                "properties": {
                    "model": {"type": "string"},
                    "learning_rate": {"type": "number", "minimum": 0.01},
                },
                "additionalProperties": False,
            },
        )

    def test_content_preview_generates_patch_without_mutation(self) -> None:
        document = self._create_document()
        candidate = {
            "model": "candidate",
            "learning_rate": 0.001,
            "nested": {"keep": 2, "new": True},
            "items": [{"id": "a"}, {"id": "b2"}],
            "added": [1],
        }

        preview = preview_document_content_update(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content=candidate,
        )

        self.assertFalse(preview["persisted"])
        self.assertEqual(preview["candidate_content"], candidate)
        self.assertEqual(preview["generated_patch"], [
            {"op": "add", "path": "/added", "value": [1]},
            {"op": "replace", "path": "/items/1/id", "value": "b2"},
            {"op": "replace", "path": "/model", "value": "candidate"},
            {"op": "replace", "path": "/nested/keep", "value": 2},
            {"op": "add", "path": "/nested/new", "value": True},
            {"op": "remove", "path": "/items/2"},
            {"op": "remove", "path": "/obsolete"},
        ])
        self.assertEqual(preview["changed_paths"], [operation["path"] for operation in preview["generated_patch"]])
        self.assertEqual(self._event_count(document["id"]), 1)
        self.assertEqual(self._document_version(document["id"]), 1)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_content_update_stores_generated_patch_event_and_replays(self) -> None:
        document = self._create_document()
        candidate = {
            "model": "candidate",
            "learning_rate": 0.01,
            "nested": {"keep": 1},
            "items": [{"id": "a"}, {"id": "b"}],
        }

        updated = update_document_content(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content=candidate,
            reason="raw editor save",
        )

        self.assertEqual(updated["current_version"], 2)
        self.assertEqual(updated["event_type"], "update")
        self.assertEqual(updated["content"], candidate)
        self.assertEqual(updated["generated_patch"], [
            {"op": "replace", "path": "/learning_rate", "value": 0.01},
            {"op": "replace", "path": "/model", "value": "candidate"},
            {"op": "remove", "path": "/items/2"},
            {"op": "remove", "path": "/obsolete"},
        ])
        history = get_history(self.db_path, document["id"], actor_id=self.actor_id)["events"]
        self.assertEqual(history[1]["id"], updated["event_id"])
        self.assertEqual(history[1]["patch"], updated["generated_patch"])
        self.assertEqual(history[1]["reason"], "raw editor save")
        self.assertEqual(history[1]["changed_paths"], [operation["path"] for operation in updated["generated_patch"]])
        self.assertEqual(self._event_count(document["id"]), 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_content_text_preview_and_update_parse_json_text(self) -> None:
        document = self._create_document()
        content_text = """
        {
          "model": "text-save",
          "learning_rate": 0.03,
          "nested": {"keep": 1},
          "items": [{"id": "a"}]
        }
        """

        preview = preview_document_content_update(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content_text=content_text,
        )
        updated = update_document_content(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content_text=content_text,
            reason="raw text editor save",
        )

        self.assertEqual(preview["content_source"], "content_text")
        self.assertFalse(preview["persisted"])
        self.assertEqual(updated["content_source"], "content_text")
        self.assertEqual(updated["current_version"], 2)
        self.assertEqual(updated["content"]["model"], "text-save")
        self.assertEqual(updated["generated_patch"], preview["generated_patch"])
        history = get_history(self.db_path, document["id"], actor_id=self.actor_id)["events"]
        self.assertEqual(history[1]["patch"], updated["generated_patch"])
        self.assertEqual(history[1]["reason"], "raw text editor save")
        self.assertEqual(self._event_count(document["id"]), 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_content_update_failures_do_not_write_partial_state(self) -> None:
        document = self._create_document()
        before_snapshot = self._document_snapshot_json(document["id"])

        with self.assertRaises(AppError) as noop:
            update_document_content(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
                content=document["content"],
            )
        with self.assertRaises(AppError) as conflict:
            update_document_content(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=0,
                content={"value": 2},
            )
        with self.assertRaises(AppError) as scalar:
            update_document_content(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
                content="not a canonical document",
            )

        self.assertEqual(noop.exception.code, ErrorCode.PATCH_APPLY_FAILED)
        self.assertEqual(conflict.exception.code, ErrorCode.VERSION_CONFLICT)
        self.assertEqual(scalar.exception.code, ErrorCode.INVALID_JSON_SYNTAX)
        self.assertEqual(self._event_count(document["id"]), 1)
        self.assertEqual(self._document_version(document["id"]), 1)
        self.assertEqual(self._document_snapshot_json(document["id"]), before_snapshot)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_content_text_failures_do_not_write_partial_state(self) -> None:
        document = self._create_document()
        before_snapshot = self._document_snapshot_json(document["id"])

        with self.assertRaises(AppError) as malformed:
            update_document_content(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
                content_text='{"model": "broken", "learning_rate": }',
            )
        with self.assertRaises(AppError) as ambiguous:
            preview_document_content_update(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
                content={"model": "candidate"},
                content_text='{"model": "candidate"}',
            )
        with self.assertRaises(AppError) as missing:
            preview_document_content_update(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
            )

        self.assertEqual(malformed.exception.code, ErrorCode.INVALID_JSON_SYNTAX)
        self.assertEqual(malformed.exception.details["source"], "content_text")
        self.assertEqual(malformed.exception.details["field"], "content_text")
        self.assertGreaterEqual(malformed.exception.details["line"], 1)
        self.assertGreaterEqual(malformed.exception.details["column"], 1)
        self.assertEqual(ambiguous.exception.code, ErrorCode.INVALID_REQUEST)
        self.assertTrue(ambiguous.exception.details["content_provided"])
        self.assertTrue(ambiguous.exception.details["content_text_provided"])
        self.assertEqual(missing.exception.code, ErrorCode.INVALID_REQUEST)
        self.assertFalse(missing.exception.details["content_provided"])
        self.assertFalse(missing.exception.details["content_text_provided"])
        self.assertEqual(self._event_count(document["id"]), 1)
        self.assertEqual(self._document_version(document["id"]), 1)
        self.assertEqual(self._document_snapshot_json(document["id"]), before_snapshot)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_schema_invalid_content_update_rejects_without_partial_write(self) -> None:
        schema = self._model_schema()
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/schema-bound.json",
            schema_id=schema["id"],
            content={"model": "baseline", "learning_rate": 0.1},
        )

        with self.assertRaises(AppError) as raised:
            update_document_content(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
                content={"model": "candidate", "learning_rate": 0.001},
            )

        self.assertEqual(raised.exception.code, ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(self._event_count(document["id"]), 1)
        self.assertEqual(self._document_version(document["id"]), 1)
        self.assertEqual(self._document_snapshot_json(document["id"]), '{"learning_rate":0.1,"model":"baseline"}')
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_content_conflict_preview_reports_stale_client_and_server_changes_without_mutation(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/conflict-preview.json",
            content={"value": 1, "label": "initial", "nested": {"a": 1}},
        )
        update_document_content(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content={"value": 2, "label": "initial", "nested": {"a": 1}},
        )

        preview = preview_document_content_conflict(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content={"value": 3, "label": "client", "nested": {"a": 1}},
        )

        self.assertFalse(preview["persisted"])
        self.assertEqual(preview["base_version"], 1)
        self.assertEqual(preview["current_version"], 2)
        self.assertEqual(preview["base_content"], {"value": 1, "label": "initial", "nested": {"a": 1}})
        self.assertEqual(preview["current_content"], {"value": 2, "label": "initial", "nested": {"a": 1}})
        self.assertEqual(preview["candidate_content"], {"value": 3, "label": "client", "nested": {"a": 1}})
        self.assertEqual(preview["client_generated_patch"], [
            {"op": "replace", "path": "/label", "value": "client"},
            {"op": "replace", "path": "/value", "value": 3},
        ])
        self.assertEqual(preview["server_generated_patch"], [
            {"op": "replace", "path": "/value", "value": 2},
        ])
        self.assertTrue(preview["has_conflicts"])
        self.assertEqual(preview["conflicting_paths"], ["/value"])
        self.assertEqual(preview["conflicts"], [
            {
                "path": "/value",
                "client_path": "/value",
                "server_path": "/value",
                "client_change_type": "modified",
                "server_change_type": "modified",
                "client_before": 1,
                "client_after": 3,
                "server_before": 1,
                "server_after": 2,
            }
        ])
        self.assertIn('"value": 2', preview["current_content_text"])
        self.assertEqual(self._event_count(document["id"]), 2)
        self.assertEqual(self._document_version(document["id"]), 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_content_conflict_preview_allows_non_conflicting_stale_changes(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/non-conflict-preview.json",
            content={"value": 1, "label": "initial"},
        )
        update_document_content(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content={"value": 2, "label": "initial"},
        )

        preview = preview_document_content_conflict(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content={"value": 1, "label": "client"},
        )

        self.assertFalse(preview["has_conflicts"])
        self.assertEqual(preview["conflicting_paths"], [])
        self.assertEqual(preview["client_changes"], [
            {"path": "/label", "change_type": "modified", "before": "initial", "after": "client"},
        ])
        self.assertEqual(preview["server_changes"], [
            {"path": "/value", "change_type": "modified", "before": 1, "after": 2},
        ])
        self.assertEqual(self._event_count(document["id"]), 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_content_conflict_preview_detects_ancestor_path_overlap_from_content_text(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/ancestor-conflict-preview.json",
            content={"value": 1, "nested": {"a": 1, "b": 2}},
        )
        update_document_content(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content={"value": 1, "nested": {"a": 9, "b": 2}},
        )

        preview = preview_document_content_conflict(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content_text='{"value":1,"nested":"reset"}',
        )

        self.assertEqual(preview["content_source"], "content_text")
        self.assertTrue(preview["has_conflicts"])
        self.assertEqual(preview["conflicting_paths"], ["/nested"])
        self.assertEqual(preview["conflicts"][0]["client_path"], "/nested")
        self.assertEqual(preview["conflicts"][0]["server_path"], "/nested/a")
        self.assertEqual(self._event_count(document["id"]), 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_content_conflict_preview_failures_do_not_write_partial_state(self) -> None:
        schema = self._model_schema()
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/schema-conflict-preview.json",
            schema_id=schema["id"],
            content={"model": "baseline", "learning_rate": 0.1},
        )
        before_snapshot = self._document_snapshot_json(document["id"])

        with self.assertRaises(AppError) as schema_failure:
            preview_document_content_conflict(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
                content={"model": "candidate", "learning_rate": 0.001},
            )
        with self.assertRaises(AppError) as future_base:
            preview_document_content_conflict(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=2,
                content={"model": "candidate", "learning_rate": 0.1},
            )

        self.assertEqual(schema_failure.exception.code, ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(future_base.exception.code, ErrorCode.INVALID_VERSION_RANGE)
        self.assertEqual(self._event_count(document["id"]), 1)
        self.assertEqual(self._document_version(document["id"]), 1)
        self.assertEqual(self._document_snapshot_json(document["id"]), before_snapshot)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_http_content_preview_and_update_routes(self) -> None:
        document = self._create_document()
        client = self._client()
        headers = {"X-Actor-Id": self.actor_id}

        preview = client.post(
            f"/documents/{document['id']}/content-preview",
            headers=headers,
            json={
                "base_version": 1,
                "content": {"model": "candidate", "learning_rate": 0.02, "nested": {"keep": 1}, "items": []},
            },
        )
        updated = client.put(
            f"/documents/{document['id']}/content",
            headers=headers,
            json={
                "base_version": 1,
                "content": {"model": "candidate", "learning_rate": 0.02, "nested": {"keep": 1}, "items": []},
                "reason": "http raw editor save",
            },
        )

        self.assertEqual(preview.status_code, 200)
        self.assertFalse(preview.json()["persisted"])
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["current_version"], 2)
        self.assertEqual(updated.json()["event_type"], "update")
        self.assertEqual(updated.json()["generated_patch"], preview.json()["generated_patch"])
        self.assertEqual(self._event_count(document["id"]), 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_http_content_text_preview_update_and_syntax_errors(self) -> None:
        document = self._create_document()
        client = self._client()
        headers = {"X-Actor-Id": self.actor_id}
        content_text = '{"model":"text-http","learning_rate":0.04,"nested":{"keep":1},"items":[]}'

        preview = client.post(
            f"/documents/{document['id']}/content-preview",
            headers=headers,
            json={"base_version": 1, "content_text": content_text},
        )
        malformed = client.post(
            f"/documents/{document['id']}/content-preview",
            headers=headers,
            json={"base_version": 1, "content_text": '{"model": }'},
        )
        ambiguous = client.post(
            f"/documents/{document['id']}/content-preview",
            headers=headers,
            json={"base_version": 1, "content": {"value": 1}, "content_text": '{"value":1}'},
        )
        updated = client.put(
            f"/documents/{document['id']}/content",
            headers=headers,
            json={"base_version": 1, "content_text": content_text, "reason": "http text save"},
        )

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["content_source"], "content_text")
        self.assertFalse(preview.json()["persisted"])
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()["error"]["code"], ErrorCode.INVALID_JSON_SYNTAX)
        self.assertEqual(malformed.json()["error"]["details"]["source"], "content_text")
        self.assertEqual(ambiguous.status_code, 400)
        self.assertEqual(ambiguous.json()["error"]["code"], ErrorCode.INVALID_REQUEST)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["content_source"], "content_text")
        self.assertEqual(updated.json()["current_version"], 2)
        self.assertEqual(updated.json()["generated_patch"], preview.json()["generated_patch"])
        self.assertEqual(self._event_count(document["id"]), 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_http_content_conflict_preview_route(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/http-conflict-preview.json",
            content={"value": 1, "label": "initial"},
        )
        update_document_content(
            self.db_path,
            document_id=document["id"],
            actor_id=self.actor_id,
            base_version=1,
            content={"value": 2, "label": "initial"},
        )
        client = self._client()
        headers = {"X-Actor-Id": self.actor_id}

        preview = client.post(
            f"/documents/{document['id']}/content-conflict-preview",
            headers=headers,
            json={"base_version": 1, "content_text": '{"value":1,"label":"client"}'},
        )
        future_base = client.post(
            f"/documents/{document['id']}/content-conflict-preview",
            headers=headers,
            json={"base_version": 3, "content": {"value": 3, "label": "client"}},
        )

        self.assertEqual(preview.status_code, 200)
        self.assertFalse(preview.json()["persisted"])
        self.assertFalse(preview.json()["has_conflicts"])
        self.assertEqual(preview.json()["content_source"], "content_text")
        self.assertEqual(preview.json()["server_changes"], [
            {"path": "/value", "change_type": "modified", "before": 1, "after": 2},
        ])
        self.assertEqual(future_base.status_code, 400)
        self.assertEqual(future_base.json()["error"]["code"], ErrorCode.INVALID_VERSION_RANGE)
        self.assertEqual(self._event_count(document["id"]), 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_api_token_content_update_uses_project_scope(self) -> None:
        document = self._create_document()
        other_document = create_document(
            self.db_path,
            project_id=self.other_project_id,
            actor_id=self.actor_id,
            full_path="config/other.json",
            content={"value": 1},
        )
        client = self._client()
        created_token = client.post(
            f"/projects/{self.project_id}/api-tokens",
            headers={"X-Actor-Id": self.actor_id},
            json={"name": "raw editor token"},
        )
        self.assertEqual(created_token.status_code, 200)
        bearer_headers = {"Authorization": f"Bearer {created_token.json()['token']}"}

        updated = client.put(
            f"/documents/{document['id']}/content",
            headers=bearer_headers,
            json={"base_version": 1, "content": {"value": 2}},
        )
        denied = client.put(
            f"/documents/{other_document['id']}/content",
            headers=bearer_headers,
            json={"base_version": 1, "content": {"value": 2}},
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["content"], {"value": 2})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(self._event_count(document["id"]), 2)
        self.assertEqual(self._event_count(other_document["id"]), 1)
        assert_replay_matches_latest(self.db_path, document["id"])
        assert_replay_matches_latest(self.db_path, other_document["id"])


if __name__ == "__main__":
    unittest.main()
