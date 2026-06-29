from __future__ import annotations

import tempfile
import unittest
import asyncio
import hashlib
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.database import connect, init_db, utc_now
from app.document_service import create_document, patch_document
from app.main import create_app
from app.realtime_service import CollaborationHub


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.messages.append(payload)


class RealtimeCollaborationTests(unittest.TestCase):
    def setUp(self) -> None:
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

    def _ws_path(self, actor_id: str | None = None) -> str:
        path = f"/ws/documents/{self.document['id']}/collaboration"
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


if __name__ == "__main__":
    unittest.main()
