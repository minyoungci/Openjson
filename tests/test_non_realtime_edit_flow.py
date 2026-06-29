from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import (
    assert_replay_matches_latest,
    create_document,
    delete_document,
    get_history,
    patch_document,
    restore_document,
    rollback_document,
)
from app.errors import ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace
from scripts.smoke_shared_edit_flow import HttpResult, SmokeFailure, _expect_status, run_shared_edit_smoke


class TestClientJsonAdapter:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: object | None = None,
        params: dict[str, object] | None = None,
    ) -> HttpResult:
        response = self.client.request(
            method,
            path,
            headers=headers,
            json=json_body,
            params=params,
        )
        try:
            body = response.json()
        except ValueError:
            body = response.text
        return HttpResult(response.status_code, body)


class NonRealtimeEditFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.editor = create_user(self.db_path, email="editor@example.com", display_name="Editor")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.editor["id"],
            role="editor",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _history_by_version(self, document_id: str) -> dict[int, dict]:
        history = get_history(self.db_path, document_id, actor_id=self.owner["id"])
        return {event["result_version"]: event for event in history["events"]}

    def _client(self) -> TestClient:
        return TestClient(create_app(self.db_path))

    def _assert_conflict_reload_details(
        self,
        body: dict,
        *,
        document: dict,
        client_base_version: int,
        server_current_version: int,
        latest_event_id: str,
        latest_event_type: str,
        latest_event_actor_id: str,
    ) -> None:
        details = body["error"]["details"]
        self.assertEqual(details["client_base_version"], client_base_version)
        self.assertEqual(details["server_current_version"], server_current_version)
        self.assertEqual(details["document_id"], document["id"])
        self.assertEqual(details["project_id"], document["project_id"])
        self.assertEqual(details["full_path"], document["full_path"])
        self.assertEqual(details["conflict_policy"], "reject_stale_base_version")
        self.assertEqual(
            details["reload"],
            {"method": "GET", "endpoint": f"/documents/{document['id']}/editor-state"},
        )
        latest_event = details["latest_event"]
        self.assertEqual(latest_event["id"], latest_event_id)
        self.assertEqual(latest_event["event_type"], latest_event_type)
        self.assertEqual(latest_event["result_version"], server_current_version)
        self.assertEqual(latest_event["actor_id"], latest_event_actor_id)

    def test_accepted_mutation_responses_return_event_metadata_matching_history(self) -> None:
        created = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/event-response.json",
            content={"value": 1, "label": "initial"},
        )
        updated = patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
        )
        deleted = delete_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            base_version=2,
        )
        restored = restore_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            base_version=3,
        )
        patched_after_restore = patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            base_version=4,
            patch=[{"op": "replace", "path": "/label", "value": "changed"}],
        )
        rolled_back = rollback_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            base_version=5,
            target_version=4,
        )

        responses = {
            1: created,
            2: updated,
            3: deleted,
            4: restored,
            5: patched_after_restore,
            6: rolled_back,
        }
        expected_types = {
            1: "create",
            2: "update",
            3: "delete",
            4: "restore",
            5: "update",
            6: "rollback",
        }
        events = self._history_by_version(created["id"])
        for version, response in responses.items():
            with self.subTest(version=version):
                self.assertEqual(response["current_version"], version)
                self.assertEqual(response["event_type"], expected_types[version])
                self.assertEqual(response["event_id"], events[version]["id"])
                self.assertEqual(events[version]["event_type"], expected_types[version])

        self.assertEqual(self._event_count(created["id"]), 6)
        assert_replay_matches_latest(self.db_path, created["id"])

    def test_two_actor_editor_state_save_conflict_reload_and_resave_flow(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/shared-edit.json",
            content={"value": 1, "label": "initial"},
        )
        client = self._client()
        owner_headers = {"X-Actor-Id": self.owner["id"]}
        editor_headers = {"X-Actor-Id": self.editor["id"]}

        owner_state = client.get(f"/documents/{document['id']}/editor-state", headers=owner_headers)
        editor_state = client.get(f"/documents/{document['id']}/editor-state", headers=editor_headers)
        self.assertEqual(owner_state.status_code, 200)
        self.assertEqual(editor_state.status_code, 200)
        self.assertEqual(owner_state.json()["editor"]["required_base_version"], 1)
        self.assertEqual(editor_state.json()["editor"]["required_base_version"], 1)

        owner_patch = client.patch(
            f"/documents/{document['id']}",
            headers=owner_headers,
            json={
                "base_version": 1,
                "patch": [{"op": "replace", "path": "/value", "value": 2}],
                "reason": "owner save",
            },
        )
        self.assertEqual(owner_patch.status_code, 200)
        self.assertEqual(owner_patch.json()["event_type"], "update")
        self.assertEqual(owner_patch.json()["current_version"], 2)
        owner_event_id = owner_patch.json()["event_id"]

        stale_preview = client.post(
            f"/documents/{document['id']}/patch-preview",
            headers=editor_headers,
            json={"base_version": 1, "patch": [{"op": "replace", "path": "/label", "value": "editor"}]},
        )
        stale_save = client.patch(
            f"/documents/{document['id']}",
            headers=editor_headers,
            json={
                "base_version": 1,
                "patch": [{"op": "replace", "path": "/label", "value": "editor"}],
                "reason": "stale editor save",
            },
        )
        self.assertEqual(stale_preview.status_code, 409)
        self.assertEqual(stale_preview.json()["error"]["code"], ErrorCode.VERSION_CONFLICT)
        self.assertEqual(stale_save.status_code, 409)
        self.assertEqual(stale_save.json()["error"]["code"], ErrorCode.VERSION_CONFLICT)
        self._assert_conflict_reload_details(
            stale_preview.json(),
            document=document,
            client_base_version=1,
            server_current_version=2,
            latest_event_id=owner_event_id,
            latest_event_type="update",
            latest_event_actor_id=self.owner["id"],
        )
        self._assert_conflict_reload_details(
            stale_save.json(),
            document=document,
            client_base_version=1,
            server_current_version=2,
            latest_event_id=owner_event_id,
            latest_event_type="update",
            latest_event_actor_id=self.owner["id"],
        )
        self.assertEqual(self._event_count(document["id"]), 2)

        reloaded = client.get(
            f"/documents/{document['id']}/editor-state",
            headers=editor_headers,
            params={"recent_events_limit": 1},
        )
        self.assertEqual(reloaded.status_code, 200)
        self.assertEqual(reloaded.json()["document"]["content"], {"value": 2, "label": "initial"})
        self.assertEqual(reloaded.json()["editor"]["required_base_version"], 2)
        self.assertEqual(reloaded.json()["recent_events"][0]["id"], owner_event_id)

        preview = client.post(
            f"/documents/{document['id']}/patch-preview",
            headers=editor_headers,
            json={"base_version": 2, "patch": [{"op": "replace", "path": "/label", "value": "editor"}]},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertFalse(preview.json()["persisted"])
        self.assertEqual(preview.json()["candidate_content"], {"value": 2, "label": "editor"})
        self.assertEqual(self._event_count(document["id"]), 2)

        editor_save = client.patch(
            f"/documents/{document['id']}",
            headers=editor_headers,
            json={
                "base_version": 2,
                "patch": [{"op": "replace", "path": "/label", "value": "editor"}],
                "reason": "editor save after reload",
            },
        )
        self.assertEqual(editor_save.status_code, 200)
        self.assertEqual(editor_save.json()["current_version"], 3)
        self.assertEqual(editor_save.json()["event_type"], "update")
        self.assertEqual(editor_save.json()["content"], {"value": 2, "label": "editor"})

        history = get_history(self.db_path, document["id"], actor_id=self.owner["id"])["events"]
        self.assertEqual([event["event_type"] for event in history], ["create", "update", "update"])
        self.assertEqual(history[1]["id"], owner_event_id)
        self.assertEqual(history[1]["actor_id"], self.owner["id"])
        self.assertEqual(history[2]["id"], editor_save.json()["event_id"])
        self.assertEqual(history[2]["actor_id"], self.editor["id"])
        self.assertEqual(self._event_count(document["id"]), 3)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_shared_edit_smoke_script_flow_succeeds_against_test_client_adapter(self) -> None:
        client = TestClientJsonAdapter(self._client())

        result = run_shared_edit_smoke(client, suffix="unit-smoke")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["final_version"], 3)
        self.assertEqual(result["workflow_mode"], "non_realtime_versioned_edit")
        self.assertEqual(result["workflow_save_content_endpoint"], f"/documents/{result['document_id']}/content")
        self.assertEqual(
            result["workflow_conflict_preview_endpoint"],
            f"/documents/{result['document_id']}/content-conflict-preview",
        )
        self.assertEqual(result["workflow_initial_state"], "clean")
        self.assertEqual(result["workflow_event_creation_only_on"], ["save_success"])
        self.assertEqual(result["bootstrap_mode"], "project_editor_bootstrap")
        self.assertEqual(result["bootstrap_selected_document_id"], result["document_id"])
        self.assertEqual(result["bootstrap_document_count"], 1)
        self.assertEqual(result["bootstrap_tree_root"], "config")
        self.assertFalse(result["bootstrap_creates_document_event"])
        self.assertEqual(result["stale_preview_error_code"], ErrorCode.VERSION_CONFLICT)
        self.assertEqual(result["stale_save_error_code"], ErrorCode.VERSION_CONFLICT)
        self.assertFalse(result["stale_conflict_preview_has_conflicts"])
        self.assertEqual(result["stale_conflict_preview_client_paths"], ["/label"])
        self.assertEqual(result["stale_conflict_preview_server_paths"], ["/value"])
        self.assertEqual(result["stale_save_latest_event_id"], result["owner_event_id"])
        self.assertEqual(result["stale_save_reload_endpoint"], f"/documents/{result['document_id']}/editor-state")
        self.assertEqual(result["history_event_types"], ["create", "update", "update"])
        self.assertEqual(result["replay_status"], "ok")
        assert_replay_matches_latest(self.db_path, result["document_id"])

    def test_shared_edit_smoke_assertion_reports_unexpected_status(self) -> None:
        with self.assertRaises(SmokeFailure) as raised:
            _expect_status(HttpResult(500, {"error": {"code": "INTERNAL_ERROR"}}), 200, "forced failure")

        self.assertIn("forced failure", str(raised.exception))
        self.assertIn("expected HTTP 200", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
