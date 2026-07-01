from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.comment_service import create_comment_thread
from app.database import connect, init_db, utc_now
from app.document_service import create_document, patch_document
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.realtime_service import CollaborationHub
from app.text_collaboration_service import text_collaboration_manager


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.messages.append(payload)


def make_zip(entries: list[tuple[str, Any]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in entries:
            archive.writestr(path, json.dumps(content))
    return buffer.getvalue()


class RealtimeCollaborationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._clear_websocket_rate_limit_env()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner_id = "user_owner"
        self.editor_id = "user_editor"
        self.viewer_id = "user_viewer"
        self.workspace_id = "workspace_001"
        self.project_id = "project_001"
        now = utc_now()
        with connect(self.db_path) as conn:
            for user_id, email, name in (
                (self.owner_id, "owner@example.com", "Owner"),
                (self.editor_id, "editor@example.com", "Editor"),
                (self.viewer_id, "viewer@example.com", "Viewer"),
            ):
                conn.execute(
                    "INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, email, name, now, now),
                )
            conn.execute(
                "INSERT INTO workspaces (id, name, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (self.workspace_id, "Workspace", self.owner_id, now, now),
            )
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (self.project_id, self.workspace_id, "Project", None, now, now),
            )
            for member_id, user_id, role in (
                ("member_owner", self.owner_id, "owner"),
                ("member_editor", self.editor_id, "editor"),
                ("member_viewer", self.viewer_id, "viewer"),
            ):
                conn.execute(
                    "INSERT INTO project_members (id, project_id, user_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (member_id, self.project_id, user_id, role, now),
                )
        self.document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.owner_id,
            full_path="config/realtime.json",
            content={"name": "baseline", "learning_rate": 0.01},
        )
        self.client = TestClient(create_app(self.db_path))

    def tearDown(self) -> None:
        self.tmp.cleanup()
        self._clear_websocket_rate_limit_env()

    def _clear_websocket_rate_limit_env(self) -> None:
        os.environ.pop("OPENJSON_WS_RATE_LIMIT_ENABLED", None)
        os.environ.pop("OPENJSON_WS_RATE_LIMIT_MESSAGES", None)
        os.environ.pop("OPENJSON_WS_RATE_LIMIT_WINDOW_SECONDS", None)

    def _ws_path(self, actor_id: str | None = None) -> str:
        path = f"/ws/documents/{self.document['id']}/collaboration"
        if actor_id:
            path += f"?actor_id={actor_id}"
        return path

    def _project_ws_path(self, actor_id: str | None = None) -> str:
        path = f"/ws/projects/{self.project_id}/workspace"
        if actor_id:
            path += f"?actor_id={actor_id}"
        return path

    def _session_ws_path(self, token: str) -> str:
        return f"/ws/documents/{self.document['id']}/collaboration?token={token}"

    def test_websocket_sends_initial_collaboration_state(self) -> None:
        with self.client.websocket_connect(self._ws_path(self.owner_id)) as websocket:
            message = websocket.receive_json()

        self.assertEqual(message["type"], "collaboration_state")
        self.assertEqual(message["reason"], "connected")
        self.assertEqual(message["state"]["document_id"], self.document["id"])
        self.assertEqual(message["state"]["current_version"], 1)

    def test_project_workspace_websocket_broadcasts_document_set_changes(self) -> None:
        with self.client.websocket_connect(self._project_ws_path(self.viewer_id)) as websocket:
            connected = websocket.receive_json()
            create_response = self.client.post(
                f"/projects/{self.project_id}/documents",
                headers={"X-Actor-Id": self.editor_id},
                json={"full_path": "config/project-ws-created.json", "content": {"value": 1}},
            )
            created_message = websocket.receive_json()
            archive = make_zip([("data/project-ws-imported.json", {"value": 2})])
            import_response = self.client.post(
                f"/projects/{self.project_id}/imports/zip-apply?reason=Project%20WS%20import",
                headers={"X-Actor-Id": self.editor_id, "Content-Type": "application/zip"},
                content=archive,
            )
            imported_message = websocket.receive_json()
            delete_response = self.client.request(
                "DELETE",
                f"/documents/{create_response.json()['id']}",
                headers={"X-Actor-Id": self.owner_id},
                json={"base_version": create_response.json()["current_version"], "reason": "Project WS delete"},
            )
            deleted_message = websocket.receive_json()
            restore_response = self.client.post(
                f"/documents/{create_response.json()['id']}/restore",
                headers={"X-Actor-Id": self.owner_id},
                json={"base_version": delete_response.json()["current_version"], "reason": "Project WS restore"},
            )
            restored_message = websocket.receive_json()

        self.assertEqual(connected["type"], "project.workspace_state")
        self.assertEqual(connected["reason"], "connected")
        self.assertEqual(connected["project_id"], self.project_id)
        self.assertEqual(connected["actor_id"], self.viewer_id)

        created = create_response.json()
        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(created_message["type"], "project.documents.changed")
        self.assertEqual(created_message["reason"], "document.created")
        self.assertEqual(created_message["project_id"], self.project_id)
        self.assertEqual(created_message["actor_id"], self.editor_id)
        self.assertEqual(created_message["documents"][0]["id"], created["id"])
        self.assertEqual(created_message["documents"][0]["full_path"], "config/project-ws-created.json")
        self.assertEqual(created_message["documents"][0]["event_type"], "create")
        self.assertEqual(created_message["documents"][0]["event_id"], created["event_id"])

        imported = import_response.json()
        self.assertEqual(import_response.status_code, 200)
        self.assertEqual(imported["imported_count"], 1)
        self.assertEqual(imported_message["type"], "project.documents.changed")
        self.assertEqual(imported_message["reason"], "documents.imported")
        self.assertEqual(imported_message["documents"][0]["id"], imported["created_documents"][0]["id"])
        self.assertEqual(imported_message["documents"][0]["full_path"], "data/project-ws-imported.json")
        self.assertEqual(imported_message["documents"][0]["event_type"], "create")

        deleted = delete_response.json()
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(deleted_message["type"], "project.documents.changed")
        self.assertEqual(deleted_message["reason"], "document.deleted")
        self.assertEqual(deleted_message["documents"][0]["id"], created["id"])
        self.assertEqual(deleted_message["documents"][0]["event_type"], "delete")
        self.assertEqual(deleted_message["documents"][0]["deleted_at"], deleted["deleted_at"])

        restored = restore_response.json()
        self.assertEqual(restore_response.status_code, 200)
        self.assertEqual(restored_message["type"], "project.documents.changed")
        self.assertEqual(restored_message["reason"], "document.restored")
        self.assertEqual(restored_message["documents"][0]["id"], created["id"])
        self.assertEqual(restored_message["documents"][0]["event_type"], "restore")
        self.assertIsNone(restored_message["documents"][0]["deleted_at"])
        self.assertEqual(restored_message["documents"][0]["event_id"], restored["event_id"])

    def test_presence_message_returns_collaboration_state(self) -> None:
        with self.client.websocket_connect(self._ws_path(self.editor_id)) as websocket:
            websocket.receive_json()
            websocket.send_json(
                {
                    "type": "presence",
                    "status": "editing",
                    "base_version": 1,
                    "dirty": True,
                    "cursor_path": "/learning_rate",
                }
            )
            update = websocket.receive_json()

        self.assertEqual(update["type"], "collaboration_state")
        self.assertEqual(update["reason"], "presence")
        active = {user["actor_id"]: user for user in update["state"]["active_users"]}
        self.assertIn(self.editor_id, active)
        self.assertEqual(active[self.editor_id]["status"], "editing")
        self.assertEqual(active[self.editor_id]["cursor_path"], "/learning_rate")

    def test_hub_broadcast_sends_to_all_registered_sockets(self) -> None:
        async def scenario() -> tuple[FakeWebSocket, FakeWebSocket]:
            hub = CollaborationHub()
            first = FakeWebSocket()
            second = FakeWebSocket()
            await hub.connect(self.document["id"], first)  # type: ignore[arg-type]
            await hub.connect(self.document["id"], second)  # type: ignore[arg-type]
            await hub.broadcast(self.document["id"], {"type": "collaboration_state", "state": {"current_version": 1}})
            return first, second

        first, second = asyncio.run(scenario())

        self.assertEqual(first.messages[0]["type"], "collaboration_state")
        self.assertEqual(second.messages[0]["type"], "collaboration_state")

    def test_refresh_after_accepted_patch_broadcasts_checkpoint_state(self) -> None:
        with self.client.websocket_connect(self._ws_path(self.owner_id)) as websocket:
            websocket.receive_json()
            patch_document(
                self.db_path,
                document_id=self.document["id"],
                actor_id=self.editor_id,
                base_version=1,
                patch=[{"op": "replace", "path": "/learning_rate", "value": 0.02}],
            )
            websocket.send_json({"type": "refresh", "since_version": 1})
            message = websocket.receive_json()

        self.assertEqual(message["type"], "collaboration_state")
        self.assertEqual(message["reason"], "refresh")
        self.assertTrue(message["state"]["has_updates"])
        self.assertEqual(message["state"]["current_version"], 2)
        self.assertEqual(message["state"]["checkpoints"][0]["result_version"], 2)

    def test_http_patch_endpoint_broadcasts_checkpoint_without_client_refresh(self) -> None:
        with self.client.websocket_connect(self._ws_path(self.owner_id)) as websocket:
            websocket.receive_json()
            response = self.client.patch(
                f"/documents/{self.document['id']}",
                headers={"X-Actor-Id": self.editor_id},
                json={
                    "base_version": 1,
                    "patch": [{"op": "replace", "path": "/learning_rate", "value": 0.02}],
                    "reason": "HTTP patch checkpoint",
                },
            )
            message = websocket.receive_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_version"], 2)
        self.assertEqual(message["type"], "collaboration_state")
        self.assertEqual(message["reason"], "document.patch")
        self.assertTrue(message["state"]["has_updates"])
        self.assertEqual(message["state"]["since_version"], 1)
        self.assertEqual(message["state"]["current_version"], 2)
        self.assertEqual(message["state"]["checkpoints"][0]["event_id"], response.json()["event_id"])
        self.assertEqual(message["state"]["checkpoints"][0]["actor_id"], self.editor_id)
        self.assertEqual(message["state"]["checkpoints"][0]["display_name"], "Editor")
        self.assertEqual(message["state"]["checkpoints"][0]["changed_paths"], ["/learning_rate"])

    def test_http_content_endpoint_broadcasts_checkpoint_without_client_refresh(self) -> None:
        with self.client.websocket_connect(self._ws_path(self.viewer_id)) as websocket:
            websocket.receive_json()
            response = self.client.put(
                f"/documents/{self.document['id']}/content",
                headers={"X-Actor-Id": self.editor_id},
                json={
                    "base_version": 1,
                    "content": {"name": "saved", "learning_rate": 0.01},
                    "reason": "HTTP content checkpoint",
                },
            )
            message = websocket.receive_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_version"], 2)
        self.assertEqual(message["type"], "collaboration_state")
        self.assertEqual(message["reason"], "document.content")
        self.assertTrue(message["state"]["has_updates"])
        self.assertEqual(message["state"]["since_version"], 1)
        self.assertEqual(message["state"]["current_version"], 2)
        self.assertEqual(message["state"]["checkpoints"][0]["event_id"], response.json()["event_id"])
        self.assertEqual(message["state"]["checkpoints"][0]["changed_paths"], ["/name"])

    def test_http_rollback_endpoint_broadcasts_checkpoint_without_client_refresh(self) -> None:
        patched = patch_document(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.editor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.02}],
        )
        self.assertEqual(patched["current_version"], 2)

        with self.client.websocket_connect(self._ws_path(self.editor_id)) as websocket:
            websocket.receive_json()
            response = self.client.post(
                f"/documents/{self.document['id']}/rollback",
                headers={"X-Actor-Id": self.owner_id},
                json={"base_version": 2, "target_version": 1, "reason": "HTTP rollback checkpoint"},
            )
            message = websocket.receive_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_version"], 3)
        self.assertEqual(response.json()["event_type"], "rollback")
        self.assertEqual(message["type"], "collaboration_state")
        self.assertEqual(message["reason"], "document.rollback")
        self.assertTrue(message["state"]["has_updates"])
        self.assertEqual(message["state"]["since_version"], 2)
        self.assertEqual(message["state"]["current_version"], 3)
        self.assertEqual(message["state"]["checkpoints"][0]["event_id"], response.json()["event_id"])
        self.assertEqual(message["state"]["checkpoints"][0]["event_type"], "rollback")

    def test_http_delete_and_restore_endpoints_broadcast_document_lifecycle(self) -> None:
        with self.client.websocket_connect(self._ws_path(self.viewer_id)) as websocket:
            websocket.receive_json()
            deleted_response = self.client.request(
                "DELETE",
                f"/documents/{self.document['id']}",
                headers={"X-Actor-Id": self.owner_id},
                json={"base_version": 1, "reason": "HTTP delete lifecycle"},
            )
            deleted_message = websocket.receive_json()
            restored_response = self.client.post(
                f"/documents/{self.document['id']}/restore",
                headers={"X-Actor-Id": self.owner_id},
                json={"base_version": deleted_response.json()["current_version"], "reason": "HTTP restore lifecycle"},
            )
            restored_message = websocket.receive_json()

        deleted = deleted_response.json()
        restored = restored_response.json()
        self.assertEqual(deleted_response.status_code, 200)
        self.assertEqual(deleted["event_type"], "delete")
        self.assertEqual(deleted["current_version"], 2)
        self.assertIsNotNone(deleted["deleted_at"])
        self.assertEqual(deleted_message["type"], "document.lifecycle")
        self.assertEqual(deleted_message["reason"], "document.deleted")
        self.assertEqual(deleted_message["document_id"], self.document["id"])
        self.assertEqual(deleted_message["event_type"], "delete")
        self.assertEqual(deleted_message["event_id"], deleted["event_id"])
        self.assertEqual(deleted_message["previous_version"], 1)
        self.assertEqual(deleted_message["current_version"], 2)
        self.assertEqual(deleted_message["deleted_at"], deleted["deleted_at"])
        self.assertEqual(deleted_message["full_path"], self.document["full_path"])

        self.assertEqual(restored_response.status_code, 200)
        self.assertEqual(restored["event_type"], "restore")
        self.assertEqual(restored["current_version"], 3)
        self.assertIsNone(restored["deleted_at"])
        self.assertEqual(restored_message["type"], "document.lifecycle")
        self.assertEqual(restored_message["reason"], "document.restored")
        self.assertEqual(restored_message["document_id"], self.document["id"])
        self.assertEqual(restored_message["event_type"], "restore")
        self.assertEqual(restored_message["event_id"], restored["event_id"])
        self.assertEqual(restored_message["previous_version"], 2)
        self.assertEqual(restored_message["current_version"], 3)
        self.assertIsNone(restored_message["deleted_at"])
        self.assertEqual(restored_message["full_path"], self.document["full_path"])

    def test_comment_thread_endpoint_broadcasts_comment_update(self) -> None:
        with self.client.websocket_connect(self._ws_path(self.owner_id)) as websocket:
            websocket.receive_json()
            response = self.client.post(
                f"/documents/{self.document['id']}/comment-threads",
                headers={"X-Actor-Id": self.editor_id},
                json={"body": "Check this setting", "anchor_type": "path", "path": "/learning_rate"},
            )
            message = websocket.receive_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(message["type"], "comment_threads.updated")
        self.assertEqual(message["reason"], "comment_thread.created")
        self.assertEqual(message["document_id"], self.document["id"])
        self.assertEqual(message["thread_id"], response.json()["id"])
        self.assertEqual(message["status"], "open")

    def test_comment_reply_and_resolve_endpoints_broadcast_comment_updates(self) -> None:
        thread = create_comment_thread(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.owner_id,
            body="Initial note",
            anchor_type="document",
        )

        with self.client.websocket_connect(self._ws_path(self.viewer_id)) as websocket:
            websocket.receive_json()
            reply = self.client.post(
                f"/comment-threads/{thread['id']}/comments",
                headers={"X-Actor-Id": self.editor_id},
                json={"body": "Reply from editor"},
            )
            reply_message = websocket.receive_json()
            resolved = self.client.post(
                f"/comment-threads/{thread['id']}/resolve",
                headers={"X-Actor-Id": self.owner_id},
            )
            resolve_message = websocket.receive_json()

        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply_message["type"], "comment_threads.updated")
        self.assertEqual(reply_message["reason"], "comment.added")
        self.assertEqual(reply_message["document_id"], self.document["id"])
        self.assertEqual(reply_message["thread_id"], thread["id"])
        self.assertEqual(reply_message["comment_id"], reply.json()["id"])
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolve_message["type"], "comment_threads.updated")
        self.assertEqual(resolve_message["reason"], "comment_thread.resolved")
        self.assertEqual(resolve_message["document_id"], self.document["id"])
        self.assertEqual(resolve_message["thread_id"], thread["id"])
        self.assertEqual(resolve_message["status"], "resolved")

    def test_viewer_editing_presence_is_rejected_and_closed(self) -> None:
        with self.client.websocket_connect(self._ws_path(self.viewer_id)) as websocket:
            websocket.receive_json()
            websocket.send_json(
                {
                    "type": "presence",
                    "status": "editing",
                    "base_version": 1,
                    "dirty": True,
                }
            )
            message = websocket.receive_json()
            self.assertEqual(message["type"], "error")
            self.assertEqual(message["error"]["code"], "PERMISSION_DENIED")
            with self.assertRaises(WebSocketDisconnect):
                websocket.receive_json()

    def test_viewer_text_session_operation_is_rejected_without_mutating_session(self) -> None:
        with self.client.websocket_connect(self._ws_path(self.viewer_id)) as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "text_session.join"})
            state = websocket.receive_json()
            self.assertEqual(state["type"], "text_session.state")
            index = state["content_text"].index("baseline")

            websocket.send_json(
                {
                    "type": "text_session.op",
                    "client_id": "viewer-client",
                    "base_text_revision": state["text_revision"],
                    "op": {"type": "replace", "index": index, "length": len("baseline"), "text": "viewer"},
                }
            )
            rejected = websocket.receive_json()
            self.assertEqual(rejected["type"], "error")
            self.assertEqual(rejected["error"]["code"], "PERMISSION_DENIED")
            self.assertEqual(
                rejected["error"]["details"]["required_permission"],
                "document:write",
            )
            with self.assertRaises(WebSocketDisconnect):
                websocket.receive_json()

        with self.client.websocket_connect(self._ws_path(self.owner_id)) as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "text_session.join"})
            state = websocket.receive_json()

        self.assertIn("baseline", state["content_text"])
        self.assertNotIn("viewer", state["content_text"])

    def test_duplicate_text_session_operation_is_idempotent(self) -> None:
        with self.client.websocket_connect(self._ws_path(self.owner_id)) as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "text_session.join"})
            state = websocket.receive_json()
            index = state["content_text"].index("baseline")
            operation = {
                "type": "text_session.op",
                "client_id": "owner-client",
                "client_operation_id": "owner-op-1",
                "base_text_revision": state["text_revision"],
                "op": {"type": "insert", "index": index, "text": "X"},
            }

            websocket.send_json(operation)
            accepted = websocket.receive_json()
            self.assertEqual(accepted["type"], "text_session.op.accepted")
            self.assertFalse(accepted["idempotent_replay"])
            self.assertEqual(accepted["server_text_revision"], 1)
            self.assertIn('"name":"Xbaseline"', accepted["content_text"].replace(" ", ""))

            websocket.send_json(operation)
            replayed = websocket.receive_json()
            self.assertEqual(replayed["type"], "text_session.op.accepted")
            self.assertTrue(replayed["idempotent_replay"])
            self.assertEqual(replayed["server_text_revision"], accepted["server_text_revision"])
            self.assertEqual(replayed["client_operation_id"], "owner-op-1")
            self.assertEqual(replayed["content_text"], accepted["content_text"])

            websocket.send_json({"type": "text_session.commit", "text_revision": replayed["server_text_revision"]})
            committed = websocket.receive_json()
            self.assertEqual(committed["type"], "text_session.committed")
            self.assertEqual(committed["result_version"], 2)

        loaded = self.client.get(f"/documents/{self.document['id']}", headers={"X-Actor-Id": self.owner_id})
        self.assertEqual(loaded.json()["content"]["name"], "Xbaseline")

    def test_stale_delete_after_concurrent_insert_preserves_inserted_text(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.owner_id,
            full_path="config/text-transform-delete.json",
            content={"text": "abc"},
        )

        async def scenario() -> dict[str, Any]:
            state = await text_collaboration_manager.join(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
            )
            index = state["content_text"].index("b")
            first = await text_collaboration_manager.apply_operation(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
                message={
                    "client_id": "owner-client",
                    "client_operation_id": "owner-insert-before-b",
                    "base_text_revision": state["text_revision"],
                    "op": {"type": "insert", "index": index, "text": "X"},
                },
            )
            second = await text_collaboration_manager.apply_operation(
                self.db_path,
                document_id=document["id"],
                actor_id=self.editor_id,
                message={
                    "client_id": "editor-client",
                    "client_operation_id": "editor-delete-b",
                    "base_text_revision": state["text_revision"],
                    "op": {"type": "delete", "index": index, "length": 1},
                },
            )
            committed = await text_collaboration_manager.commit(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
                message={"text_revision": second["server_text_revision"]},
            )
            return {"first": first, "second": second, "committed": committed}

        result = asyncio.run(scenario())

        self.assertEqual(result["first"]["op"], {"type": "insert", "index": result["second"]["op"]["index"] - 1, "text": "X"})
        self.assertEqual(result["second"]["op"]["type"], "delete")
        loaded = self.client.get(f"/documents/{document['id']}", headers={"X-Actor-Id": self.owner_id})
        self.assertEqual(loaded.json()["content"], {"text": "aXc"})

    def test_stale_delete_requiring_split_is_rejected_without_mutating_text(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.owner_id,
            full_path="config/text-transform-conflict.json",
            content={"text": "abcd"},
        )

        async def scenario() -> tuple[dict[str, Any], AppError, dict[str, Any]]:
            state = await text_collaboration_manager.join(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
            )
            insert_index = state["content_text"].index("c")
            delete_index = state["content_text"].index("b")
            accepted = await text_collaboration_manager.apply_operation(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
                message={
                    "client_id": "owner-client",
                    "client_operation_id": "owner-insert-before-c",
                    "base_text_revision": state["text_revision"],
                    "op": {"type": "insert", "index": insert_index, "text": "X"},
                },
            )
            try:
                await text_collaboration_manager.apply_operation(
                    self.db_path,
                    document_id=document["id"],
                    actor_id=self.editor_id,
                    message={
                        "client_id": "editor-client",
                        "client_operation_id": "editor-delete-bc",
                        "base_text_revision": state["text_revision"],
                        "op": {"type": "delete", "index": delete_index, "length": 2},
                    },
                )
            except AppError as exc:
                conflict = exc
            else:
                raise AssertionError("Expected stale text transform conflict")
            current = await text_collaboration_manager.join(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
            )
            return accepted, conflict, current

        accepted, conflict, current = asyncio.run(scenario())

        self.assertEqual(conflict.code, ErrorCode.VERSION_CONFLICT)
        self.assertEqual(conflict.details["conflict_policy"], "reject_unsafe_text_transform")
        self.assertEqual(current["text_revision"], accepted["server_text_revision"])
        self.assertIn('"text": "abXcd"', current["content_text"])
        loaded = self.client.get(f"/documents/{document['id']}", headers={"X-Actor-Id": self.owner_id})
        self.assertEqual(loaded.json()["content"], {"text": "abcd"})

    def test_out_of_bounds_text_operations_are_rejected_without_advancing_revision(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.owner_id,
            full_path="config/text-bounds.json",
            content={"text": "abc"},
        )

        async def scenario() -> tuple[dict[str, Any], list[AppError], dict[str, Any]]:
            state = await text_collaboration_manager.join(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
            )
            invalid_ops = [
                ("insert", {"type": "insert", "index": len(state["content_text"]) + 10, "text": "X"}),
                ("delete", {"type": "delete", "index": len(state["content_text"]), "length": 1}),
                ("replace", {"type": "replace", "index": len(state["content_text"]) - 1, "length": 2, "text": "X"}),
            ]
            errors: list[AppError] = []
            for index, (op_type, op) in enumerate(invalid_ops):
                try:
                    await text_collaboration_manager.apply_operation(
                        self.db_path,
                        document_id=document["id"],
                        actor_id=self.owner_id,
                        message={
                            "client_id": "owner-client",
                            "client_operation_id": f"owner-{op_type}-out-of-bounds",
                            "base_text_revision": state["text_revision"],
                            "op": op,
                        },
                    )
                except AppError as exc:
                    errors.append(exc)
                else:
                    raise AssertionError(f"Expected out-of-bounds {op_type} rejection at {index}")
            current = await text_collaboration_manager.join(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
            )
            return state, errors, current

        before, errors, after = asyncio.run(scenario())

        self.assertEqual([error.code for error in errors], [ErrorCode.INVALID_REQUEST] * 3)
        self.assertEqual(errors[0].details["reason"], "insert_index_exceeds_text_length")
        self.assertEqual(errors[1].details["reason"], "operation_range_exceeds_text_length")
        self.assertEqual(errors[2].details["reason"], "operation_range_exceeds_text_length")
        self.assertEqual(after["text_revision"], before["text_revision"])
        self.assertEqual(after["content_text"], before["content_text"])

    def test_text_session_join_resets_after_external_document_version_change(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.owner_id,
            full_path="config/text-version-drift.json",
            content={"text": "abc"},
        )

        async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
            state = await text_collaboration_manager.join(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
            )
            accepted = await text_collaboration_manager.apply_operation(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
                message={
                    "client_id": "owner-client",
                    "client_operation_id": "owner-uncommitted-insert",
                    "base_text_revision": state["text_revision"],
                    "op": {"type": "insert", "index": state["content_text"].index("b"), "text": "X"},
                },
            )
            patch_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.editor_id,
                base_version=1,
                patch=[{"op": "replace", "path": "/text", "value": "server"}],
            )
            reset = await text_collaboration_manager.join(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
            )
            return accepted, reset

        accepted, reset = asyncio.run(scenario())

        self.assertEqual(accepted["server_text_revision"], 1)
        self.assertEqual(reset["type"], "text_session.state")
        self.assertTrue(reset["session_reset"])
        self.assertEqual(reset["reset_reason"], "document_version_changed")
        self.assertEqual(reset["previous_document_version"], 1)
        self.assertEqual(reset["previous_text_revision"], 1)
        self.assertEqual(reset["document_version"], 2)
        self.assertEqual(reset["text_revision"], 0)
        self.assertIn('"server"', reset["content_text"])
        self.assertNotIn("aXbc", reset["content_text"])
        loaded = self.client.get(f"/documents/{document['id']}", headers={"X-Actor-Id": self.owner_id})
        self.assertEqual(loaded.json()["content"], {"text": "server"})

    def test_text_session_operation_after_reset_conflicts_without_mutating_text(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.owner_id,
            full_path="config/text-reset-conflict.json",
            content={"text": "abc"},
        )

        async def scenario() -> tuple[dict[str, Any], AppError, dict[str, Any]]:
            state = await text_collaboration_manager.join(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
            )
            accepted = await text_collaboration_manager.apply_operation(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
                message={
                    "client_id": "owner-client",
                    "client_operation_id": "owner-old-insert",
                    "base_text_revision": state["text_revision"],
                    "op": {"type": "insert", "index": state["content_text"].index("b"), "text": "X"},
                },
            )
            patch_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.editor_id,
                base_version=1,
                patch=[{"op": "replace", "path": "/text", "value": "server"}],
            )
            try:
                await text_collaboration_manager.apply_operation(
                    self.db_path,
                    document_id=document["id"],
                    actor_id=self.owner_id,
                    message={
                        "client_id": "owner-client",
                        "client_operation_id": "owner-stale-after-reset",
                        "base_text_revision": accepted["server_text_revision"],
                        "op": {"type": "insert", "index": 0, "text": "Z"},
                    },
                )
            except AppError as exc:
                conflict = exc
            else:
                raise AssertionError("Expected reset text revision conflict")
            current = await text_collaboration_manager.join(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
            )
            return accepted, conflict, current

        accepted, conflict, current = asyncio.run(scenario())

        self.assertEqual(accepted["server_text_revision"], 1)
        self.assertEqual(conflict.code, ErrorCode.VERSION_CONFLICT)
        self.assertEqual(conflict.details["conflict_policy"], "reject_ahead_text_revision")
        self.assertEqual(conflict.details["client_text_revision"], 1)
        self.assertEqual(conflict.details["server_text_revision"], 0)
        self.assertEqual(current["document_version"], 2)
        self.assertEqual(current["text_revision"], 0)
        self.assertIn('"server"', current["content_text"])
        self.assertNotIn("Z", current["content_text"])

    def test_missing_actor_websocket_gets_structured_error(self) -> None:
        with self.client.websocket_connect(self._ws_path()) as websocket:
            message = websocket.receive_json()
            self.assertEqual(message["type"], "error")
            self.assertEqual(message["error"]["code"], "AUTH_REQUIRED")
            with self.assertRaises(WebSocketDisconnect):
                websocket.receive_json()

    def test_websocket_accepts_session_token_query(self) -> None:
        token = "ojs_test_session_secret"
        now = utc_now()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO user_sessions (
                    id,
                    user_id,
                    token_prefix,
                    token_hash,
                    created_at,
                    expires_at,
                    last_used_at,
                    revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    "sess_ws",
                    self.owner_id,
                    token[:12],
                    hashlib.sha256(token.encode("utf-8")).hexdigest(),
                    now,
                    "2999-01-01T00:00:00Z",
                    now,
                ),
            )

        with self.client.websocket_connect(self._session_ws_path(token)) as websocket:
            message = websocket.receive_json()

        self.assertEqual(message["type"], "collaboration_state")
        self.assertEqual(message["state"]["actor_id"], self.owner_id)

    def test_websocket_message_rate_limit_sends_error_and_closes(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENJSON_WS_RATE_LIMIT_ENABLED": "1",
                "OPENJSON_WS_RATE_LIMIT_MESSAGES": "2",
                "OPENJSON_WS_RATE_LIMIT_WINDOW_SECONDS": "60",
            },
            clear=False,
        ):
            client = TestClient(create_app(self.db_path))
            with client.websocket_connect(self._ws_path(self.owner_id)) as websocket:
                websocket.receive_json()
                websocket.send_json({"type": "ping"})
                self.assertEqual(websocket.receive_json()["type"], "pong")
                websocket.send_json({"type": "ping"})
                self.assertEqual(websocket.receive_json()["type"], "pong")
                websocket.send_json({"type": "ping"})
                limited = websocket.receive_json()
                self.assertEqual(limited["type"], "error")
                self.assertEqual(limited["error"]["code"], "RATE_LIMITED")
                self.assertEqual(limited["error"]["details"]["limit"], 2)
                self.assertEqual(limited["error"]["details"]["window_seconds"], 60)
                with self.assertRaises(WebSocketDisconnect):
                    websocket.receive_json()


if __name__ == "__main__":
    unittest.main()
