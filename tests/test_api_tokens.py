from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import assert_replay_matches_latest, create_document, get_history
from app.errors import ErrorCode
from app.main import create_app
from app.schema_service import create_schema
from app.workspace_service import create_project, create_user, create_workspace


class ApiTokenAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.other_user = create_user(self.db_path, email="other@example.com", display_name="Other")
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

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _client(self) -> TestClient:
        return TestClient(create_app(self.db_path))

    def _create_token(self, client: TestClient, name: str = "ci token") -> dict:
        response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": name},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_create_list_and_store_hashed_project_api_token(self) -> None:
        client = self._client()
        created = self._create_token(client)

        self.assertTrue(created["token"].startswith("ojt_"))
        self.assertEqual(created["token_prefix"], created["token"][:12])
        self.assertEqual(created["project_id"], self.project["id"])
        self.assertEqual(created["user_id"], self.owner["id"])
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (created["id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["token_hash"], created["token"])
        self.assertEqual(row["token_prefix"], created["token_prefix"])

        listed = client.get(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["api_tokens"][0]["id"], created["id"])
        self.assertNotIn("token", listed.json()["api_tokens"][0])

    def test_bearer_token_authenticates_project_and_document_requests(self) -> None:
        client = self._client()
        created = self._create_token(client)
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/token.json",
            content={"value": 1},
        )

        project_response = client.get(
            f"/projects/{self.project['id']}",
            headers={"Authorization": f"Bearer {created['token']}"},
        )
        document_response = client.get(
            f"/documents/{document['id']}",
            headers={"Authorization": f"Bearer {created['token']}"},
        )

        self.assertEqual(project_response.status_code, 200)
        self.assertEqual(project_response.json()["role"], "owner")
        self.assertEqual(document_response.status_code, 200)
        self.assertEqual(document_response.json()["id"], document["id"])
        with connect(self.db_path) as conn:
            token_row = conn.execute("SELECT last_used_at FROM api_tokens WHERE id = ?", (created["id"],)).fetchone()
        self.assertIsNotNone(token_row["last_used_at"])

    def test_bearer_token_document_mutations_use_token_owner_as_event_actor(self) -> None:
        client = self._client()
        created = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created['token']}"}

        created_document = client.post(
            f"/projects/{self.project['id']}/documents",
            headers=bearer_headers,
            json={
                "full_path": "config/token-mutation.json",
                "content": {"value": 1, "enabled": True},
            },
        )
        self.assertEqual(created_document.status_code, 200)
        document_id = created_document.json()["id"]
        self.assertEqual(created_document.json()["created_by"], self.owner["id"])

        patched_document = client.patch(
            f"/documents/{document_id}",
            headers=bearer_headers,
            json={
                "base_version": 1,
                "patch": [{"op": "replace", "path": "/value", "value": 2}],
                "reason": "token patch",
            },
        )
        self.assertEqual(patched_document.status_code, 200)
        self.assertEqual(patched_document.json()["current_version"], 2)
        self.assertEqual(patched_document.json()["content"]["value"], 2)

        deleted_document = client.request(
            "DELETE",
            f"/documents/{document_id}",
            headers=bearer_headers,
            json={"base_version": 2, "reason": "token delete"},
        )
        self.assertEqual(deleted_document.status_code, 200)
        self.assertEqual(deleted_document.json()["current_version"], 3)
        self.assertIsNotNone(deleted_document.json()["deleted_at"])

        history = client.get(f"/documents/{document_id}/history", headers=bearer_headers)
        self.assertEqual(history.status_code, 200)
        events = history.json()["events"]
        self.assertEqual([event["event_type"] for event in events], ["create", "update", "delete"])
        self.assertEqual([event["actor_id"] for event in events], [self.owner["id"]] * 3)
        self.assertEqual(events[1]["reason"], "token patch")
        self.assertEqual(events[2]["reason"], "token delete")
        self.assertEqual(events[1]["changed_paths"], ["/value"])
        assert_replay_matches_latest(self.db_path, document_id)

    def test_bearer_token_restore_uses_token_owner_as_event_actor(self) -> None:
        client = self._client()
        created = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created['token']}"}
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/token-restore.json",
            content={"value": 1},
        )

        deleted_document = client.request(
            "DELETE",
            f"/documents/{document['id']}",
            headers=bearer_headers,
            json={"base_version": 1, "reason": "token delete before restore"},
        )
        self.assertEqual(deleted_document.status_code, 200)
        self.assertIsNotNone(deleted_document.json()["deleted_at"])

        restored_document = client.post(
            f"/documents/{document['id']}/restore",
            headers=bearer_headers,
            json={"base_version": 2, "reason": "token restore"},
        )
        self.assertEqual(restored_document.status_code, 200)
        self.assertEqual(restored_document.json()["current_version"], 3)
        self.assertIsNone(restored_document.json()["deleted_at"])

        history = client.get(f"/documents/{document['id']}/history", headers=bearer_headers)
        self.assertEqual(history.status_code, 200)
        events = history.json()["events"]
        self.assertEqual([event["event_type"] for event in events], ["create", "delete", "restore"])
        self.assertEqual([event["actor_id"] for event in events], [self.owner["id"]] * 3)
        self.assertEqual(events[1]["reason"], "token delete before restore")
        self.assertEqual(events[2]["reason"], "token restore")
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_bearer_token_rollback_uses_token_owner_as_event_actor(self) -> None:
        client = self._client()
        created = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created['token']}"}
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/token-rollback.json",
            content={"value": 1, "enabled": True},
        )

        patched_document = client.patch(
            f"/documents/{document['id']}",
            headers=bearer_headers,
            json={
                "base_version": 1,
                "patch": [{"op": "replace", "path": "/value", "value": 2}],
                "reason": "token patch before rollback",
            },
        )
        self.assertEqual(patched_document.status_code, 200)
        self.assertEqual(patched_document.json()["content"]["value"], 2)

        rolled_back_document = client.post(
            f"/documents/{document['id']}/rollback",
            headers=bearer_headers,
            json={"base_version": 2, "target_version": 1, "reason": "token rollback"},
        )
        self.assertEqual(rolled_back_document.status_code, 200)
        self.assertEqual(rolled_back_document.json()["current_version"], 3)
        self.assertEqual(rolled_back_document.json()["rollback_target_version"], 1)
        self.assertEqual(rolled_back_document.json()["content"]["value"], 1)

        history = client.get(f"/documents/{document['id']}/history", headers=bearer_headers)
        self.assertEqual(history.status_code, 200)
        events = history.json()["events"]
        self.assertEqual([event["event_type"] for event in events], ["create", "update", "rollback"])
        self.assertEqual([event["actor_id"] for event in events], [self.owner["id"]] * 3)
        self.assertEqual(events[1]["reason"], "token patch before rollback")
        self.assertEqual(events[2]["reason"], "token rollback")
        self.assertEqual(events[2]["changed_paths"], ["/value"])
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_bearer_token_patch_preview_uses_project_scope_without_document_event(self) -> None:
        client = self._client()
        created = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created['token']}"}
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/token-preview.json",
            content={"value": 1, "enabled": True},
        )
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other-token-preview.json",
            content={"value": 1},
        )

        preview = client.post(
            f"/documents/{document['id']}/patch-preview",
            headers=bearer_headers,
            json={"base_version": 1, "patch": [{"op": "replace", "path": "/value", "value": 2}]},
        )
        denied_preview = client.post(
            f"/documents/{other_document['id']}/patch-preview",
            headers=bearer_headers,
            json={"base_version": 1, "patch": [{"op": "replace", "path": "/value", "value": 2}]},
        )

        self.assertEqual(preview.status_code, 200)
        self.assertFalse(preview.json()["persisted"])
        self.assertEqual(preview.json()["candidate_content"], {"value": 2, "enabled": True})
        self.assertEqual(preview.json()["changed_paths"], ["/value"])
        self.assertEqual(preview.json()["inverse_patch"], [{"op": "replace", "path": "/value", "value": 1}])
        self.assertEqual(denied_preview.status_code, 403)
        self.assertEqual(denied_preview.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

        history = get_history(self.db_path, document["id"], actor_id=self.owner["id"])
        other_history = get_history(self.db_path, other_document["id"], actor_id=self.owner["id"])
        self.assertEqual([event["event_type"] for event in history["events"]], ["create"])
        self.assertEqual([event["event_type"] for event in other_history["events"]], ["create"])
        with connect(self.db_path) as conn:
            document_row = conn.execute(
                "SELECT current_version, current_snapshot_json FROM json_documents WHERE id = ?",
                (document["id"],),
            ).fetchone()
            other_document_row = conn.execute(
                "SELECT current_version, current_snapshot_json FROM json_documents WHERE id = ?",
                (other_document["id"],),
            ).fetchone()
            token_row = conn.execute("SELECT last_used_at FROM api_tokens WHERE id = ?", (created["id"],)).fetchone()
        self.assertEqual(document_row["current_version"], 1)
        self.assertEqual(document_row["current_snapshot_json"], '{"enabled":true,"value":1}')
        self.assertEqual(other_document_row["current_version"], 1)
        self.assertEqual(other_document_row["current_snapshot_json"], '{"value":1}')
        self.assertIsNotNone(token_row["last_used_at"])
        assert_replay_matches_latest(self.db_path, document["id"])
        assert_replay_matches_latest(self.db_path, other_document["id"])

    def test_bearer_token_replay_read_surfaces_use_event_log_and_scope(self) -> None:
        client = self._client()
        created = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created['token']}"}

        created_document = client.post(
            f"/projects/{self.project['id']}/documents",
            headers=bearer_headers,
            json={
                "full_path": "config/token-replay-reads.json",
                "content": {"value": 1, "enabled": True},
            },
        )
        self.assertEqual(created_document.status_code, 200)
        document_id = created_document.json()["id"]
        patched_document = client.patch(
            f"/documents/{document_id}",
            headers=bearer_headers,
            json={
                "base_version": 1,
                "patch": [{"op": "replace", "path": "/value", "value": 2}],
                "reason": "token replay read patch",
            },
        )
        self.assertEqual(patched_document.status_code, 200)
        history = client.get(f"/documents/{document_id}/history", headers=bearer_headers)
        update_event = next(event for event in history.json()["events"] if event["event_type"] == "update")

        version_one = client.get(f"/documents/{document_id}/history/1", headers=bearer_headers)
        diff = client.get(
            f"/documents/{document_id}/diff",
            headers=bearer_headers,
            params={"from_version": 1, "to_version": 2},
        )
        detail = client.get(
            f"/documents/{document_id}/events/{update_event['id']}",
            headers=bearer_headers,
            params={"include_snapshots": "true"},
        )

        self.assertEqual(version_one.status_code, 200)
        self.assertEqual(version_one.json()["version"], 1)
        self.assertEqual(version_one.json()["content"], {"value": 1, "enabled": True})
        self.assertEqual(version_one.json()["event"]["event_type"], "create")
        self.assertEqual(diff.status_code, 200)
        self.assertEqual(diff.json()["changes"], [{"path": "/value", "change_type": "modified", "before": 1, "after": 2}])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["event"]["id"], update_event["id"])
        self.assertEqual(detail.json()["event"]["changed_paths"], ["/value"])
        self.assertEqual(detail.json()["snapshots"]["before"], {"value": 1, "enabled": True})
        self.assertEqual(detail.json()["snapshots"]["after"], {"value": 2, "enabled": True})

        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other-replay-reads.json",
            content={"value": 1},
        )
        other_history = get_history(self.db_path, other_document["id"], actor_id=self.owner["id"])
        other_event_id = other_history["events"][0]["id"]

        denied_version = client.get(f"/documents/{other_document['id']}/history/1", headers=bearer_headers)
        denied_diff = client.get(
            f"/documents/{other_document['id']}/diff",
            headers=bearer_headers,
            params={"from_version": 1, "to_version": 1},
        )
        denied_detail = client.get(
            f"/documents/{other_document['id']}/events/{other_event_id}",
            headers=bearer_headers,
            params={"include_snapshots": "true"},
        )

        self.assertEqual(denied_version.status_code, 403)
        self.assertEqual(denied_version.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(denied_diff.status_code, 403)
        self.assertEqual(denied_diff.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(denied_detail.status_code, 403)
        self.assertEqual(denied_detail.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        assert_replay_matches_latest(self.db_path, document_id)

    def test_bearer_token_path_history_and_blame_use_event_log_and_scope(self) -> None:
        client = self._client()
        created = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created['token']}"}

        created_document = client.post(
            f"/projects/{self.project['id']}/documents",
            headers=bearer_headers,
            json={
                "full_path": "config/token-path-history.json",
                "content": {"value": 1, "enabled": True},
            },
        )
        self.assertEqual(created_document.status_code, 200)
        document_id = created_document.json()["id"]
        patched_document = client.patch(
            f"/documents/{document_id}",
            headers=bearer_headers,
            json={
                "base_version": 1,
                "patch": [{"op": "replace", "path": "/value", "value": 2}],
                "reason": "token path change",
            },
        )
        self.assertEqual(patched_document.status_code, 200)

        path_history = client.get(
            f"/documents/{document_id}/path-history",
            headers=bearer_headers,
            params={"path": "/value"},
        )
        blame = client.get(
            f"/documents/{document_id}/blame",
            headers=bearer_headers,
            params={"path": "/value"},
        )

        self.assertEqual(path_history.status_code, 200)
        self.assertEqual(path_history.json()["latest"], {"exists": True, "value": 2})
        self.assertEqual([change["event_type"] for change in path_history.json()["changes"]], ["create", "update"])
        self.assertEqual([change["actor_id"] for change in path_history.json()["changes"]], [self.owner["id"]] * 2)
        self.assertEqual(path_history.json()["changes"][1]["before"], {"exists": True, "value": 1})
        self.assertEqual(path_history.json()["changes"][1]["after"], {"exists": True, "value": 2})
        self.assertEqual(path_history.json()["changes"][1]["reason"], "token path change")
        self.assertEqual(path_history.json()["blame"]["actor_id"], self.owner["id"])
        self.assertEqual(path_history.json()["blame"]["result_version"], 2)
        self.assertEqual(blame.status_code, 200)
        self.assertEqual(blame.json()["blame"], path_history.json()["blame"])

        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other-path-history.json",
            content={"value": 1},
        )
        denied_history = client.get(
            f"/documents/{other_document['id']}/path-history",
            headers=bearer_headers,
            params={"path": "/value"},
        )
        denied_blame = client.get(
            f"/documents/{other_document['id']}/blame",
            headers=bearer_headers,
            params={"path": "/value"},
        )

        self.assertEqual(denied_history.status_code, 403)
        self.assertEqual(denied_history.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(denied_blame.status_code, 403)
        self.assertEqual(denied_blame.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        assert_replay_matches_latest(self.db_path, document_id)

    def test_project_scoped_token_cannot_access_other_project_or_workspace_routes(self) -> None:
        client = self._client()
        created = self._create_token(client)
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"value": 1},
        )
        bearer_headers = {"Authorization": f"Bearer {created['token']}"}

        other_project = client.get(f"/projects/{self.other_project['id']}", headers=bearer_headers)
        other_document_response = client.get(f"/documents/{other_document['id']}", headers=bearer_headers)
        workspaces = client.get("/workspaces", headers=bearer_headers)

        self.assertEqual(other_project.status_code, 403)
        self.assertEqual(other_project.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(other_document_response.status_code, 403)
        self.assertEqual(other_document_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(workspaces.status_code, 403)
        self.assertEqual(workspaces.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

    def test_project_scoped_token_schema_scope_and_missing_schema_errors(self) -> None:
        client = self._client()
        created = self._create_token(client)
        schema = create_schema(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name="Config",
            version="1.0.0",
            schema_json={"type": "object", "properties": {"value": {"type": "number"}}},
        )
        other_schema = create_schema(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            name="Other Config",
            version="1.0.0",
            schema_json={"type": "object", "properties": {"enabled": {"type": "boolean"}}},
        )
        bearer_headers = {"Authorization": f"Bearer {created['token']}"}

        same_schema = client.get(f"/schemas/{schema['id']}", headers=bearer_headers)
        same_usage = client.get(f"/schemas/{schema['id']}/usage", headers=bearer_headers)
        other_schema_response = client.get(f"/schemas/{other_schema['id']}", headers=bearer_headers)
        other_usage_response = client.get(f"/schemas/{other_schema['id']}/usage", headers=bearer_headers)
        missing_schema = client.get("/schemas/schema_missing", headers=bearer_headers)
        missing_usage = client.get("/schemas/schema_missing/usage", headers=bearer_headers)

        self.assertEqual(same_schema.status_code, 200)
        self.assertEqual(same_schema.json()["id"], schema["id"])
        self.assertEqual(same_usage.status_code, 200)
        self.assertEqual(same_usage.json()["schema"]["id"], schema["id"])
        self.assertEqual(other_schema_response.status_code, 403)
        self.assertEqual(other_schema_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(other_usage_response.status_code, 403)
        self.assertEqual(other_usage_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(missing_schema.status_code, 404)
        self.assertEqual(missing_schema.json()["error"]["code"], ErrorCode.SCHEMA_NOT_FOUND)
        self.assertEqual(missing_usage.status_code, 404)
        self.assertEqual(missing_usage.json()["error"]["code"], ErrorCode.SCHEMA_NOT_FOUND)

    def test_revoked_invalid_and_mismatched_tokens_are_rejected(self) -> None:
        client = self._client()
        created = self._create_token(client)
        bearer_headers = {"Authorization": f"Bearer {created['token']}"}

        mismatch = client.get(
            f"/projects/{self.project['id']}",
            headers={**bearer_headers, "X-Actor-Id": self.other_user["id"]},
        )
        self.assertEqual(mismatch.status_code, 403)
        self.assertEqual(mismatch.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

        revoked = client.delete(
            f"/projects/{self.project['id']}/api-tokens/{created['id']}",
            headers=bearer_headers,
        )
        self.assertEqual(revoked.status_code, 200)
        self.assertIsNotNone(revoked.json()["revoked_at"])

        after_revoke = client.get(f"/projects/{self.project['id']}", headers=bearer_headers)
        self.assertEqual(after_revoke.status_code, 401)
        self.assertEqual(after_revoke.json()["error"]["code"], ErrorCode.AUTH_REQUIRED)

        invalid = client.get(
            f"/projects/{self.project['id']}",
            headers={"Authorization": "Bearer ojt_invalid"},
        )
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(invalid.json()["error"]["code"], ErrorCode.AUTH_REQUIRED)

        malformed = client.get(
            f"/projects/{self.project['id']}",
            headers={"Authorization": "Token nope"},
        )
        self.assertEqual(malformed.status_code, 401)
        self.assertEqual(malformed.json()["error"]["code"], ErrorCode.AUTH_REQUIRED)

    def test_token_create_revoke_audit_does_not_create_document_events_or_leak_secret(self) -> None:
        client = self._client()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/audit-token.json",
            content={"value": 1},
        )
        created = self._create_token(client, name="audit token")
        client.delete(
            f"/projects/{self.project['id']}/api-tokens/{created['id']}",
            headers={"Authorization": f"Bearer {created['token']}"},
        )

        with connect(self.db_path) as conn:
            audit_rows = conn.execute(
                """
                SELECT action, details
                FROM audit_log
                WHERE target_type = 'api_token'
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
        self.assertEqual([row["action"] for row in audit_rows], ["api_token.create", "api_token.revoke"])
        for row in audit_rows:
            self.assertNotIn(created["token"], row["details"])

        history = get_history(self.db_path, document["id"], actor_id=self.owner["id"])
        self.assertEqual([event["event_type"] for event in history["events"]], ["create"])
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_api_token_routes_are_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/api-tokens", "POST"), routes)
        self.assertIn(("/projects/{project_id}/api-tokens", "GET"), routes)
        self.assertIn(("/projects/{project_id}/api-tokens/{token_id}", "DELETE"), routes)


if __name__ == "__main__":
    unittest.main()
