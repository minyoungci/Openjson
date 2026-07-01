from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.collaboration_service import get_collaboration_state, leave_editor_presence, upsert_editor_presence
from app.database import connect, init_db, utc_now
from app.document_service import assert_replay_matches_latest, create_document, patch_document
from app.errors import AppError, ErrorCode
from app.main import create_app


class CollaborationMonitoringTests(unittest.TestCase):
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
            full_path="config/model.json",
            content={"name": "baseline", "learning_rate": 0.01},
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_presence_heartbeat_returns_active_user_state(self) -> None:
        state = upsert_editor_presence(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.owner_id,
            status="editing",
            base_version=1,
            dirty=True,
            cursor_path="/name",
        )

        self.assertEqual(state["current_version"], 1)
        self.assertEqual(len(state["active_users"]), 1)
        user = state["active_users"][0]
        self.assertEqual(user["actor_id"], self.owner_id)
        self.assertEqual(user["display_name"], "Owner")
        self.assertNotIn("email", user)
        self.assertEqual(user["status"], "editing")
        self.assertTrue(user["dirty"])
        self.assertFalse(user["is_stale_base"])
        self.assertEqual(user["cursor_path"], "/name")

    def test_checkpoint_state_reports_updates_since_loaded_version(self) -> None:
        upsert_editor_presence(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.owner_id,
            status="editing",
            base_version=1,
            dirty=True,
        )

        updated = patch_document(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.editor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.02}],
            reason="Editor checkpoint",
        )

        state = get_collaboration_state(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.owner_id,
            since_version=1,
        )

        self.assertEqual(updated["current_version"], 2)
        self.assertTrue(state["has_updates"])
        self.assertEqual(state["current_version"], 2)
        self.assertEqual(state["checkpoints"][0]["result_version"], 2)
        self.assertEqual(state["checkpoints"][0]["actor_id"], self.editor_id)
        self.assertEqual(state["checkpoints"][0]["display_name"], "Editor")
        self.assertEqual(state["checkpoints"][0]["changed_paths"], ["/learning_rate"])
        self.assertTrue(state["active_users"][0]["is_stale_base"])
        assert_replay_matches_latest(self.db_path, self.document["id"])

    def test_viewer_can_view_but_cannot_publish_editing_presence(self) -> None:
        viewing = upsert_editor_presence(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.viewer_id,
            status="viewing",
            base_version=1,
            dirty=False,
        )
        self.assertEqual(viewing["active_users"][0]["status"], "viewing")

        with self.assertRaises(AppError) as raised:
            upsert_editor_presence(
                self.db_path,
                document_id=self.document["id"],
                actor_id=self.viewer_id,
                status="editing",
                base_version=1,
                dirty=True,
            )

        self.assertEqual(raised.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_leave_presence_removes_actor_from_active_users(self) -> None:
        upsert_editor_presence(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.owner_id,
            status="viewing",
            base_version=1,
            dirty=False,
        )

        state = leave_editor_presence(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.owner_id,
        )

        self.assertEqual(state["active_users"], [])

    def test_stale_presence_rows_are_omitted(self) -> None:
        upsert_editor_presence(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.owner_id,
            status="editing",
            base_version=1,
            dirty=False,
        )
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE editor_presence SET last_seen_at = ? WHERE document_id = ?",
                ("2000-01-01T00:00:00Z", self.document["id"]),
            )

        state = get_collaboration_state(
            self.db_path,
            document_id=self.document["id"],
            actor_id=self.owner_id,
            since_version=1,
        )

        self.assertEqual(state["active_users"], [])

    def test_http_collaboration_endpoints(self) -> None:
        client = TestClient(create_app(self.db_path))

        heartbeat = client.post(
            f"/documents/{self.document['id']}/presence",
            headers={"X-Actor-Id": self.owner_id},
            json={"status": "editing", "base_version": 1, "dirty": True, "cursor_path": "/learning_rate"},
        )
        self.assertEqual(heartbeat.status_code, 200)
        self.assertEqual(heartbeat.json()["active_users"][0]["actor_id"], self.owner_id)
        self.assertEqual(heartbeat.json()["active_users"][0]["display_name"], "Owner")
        self.assertNotIn("email", heartbeat.json()["active_users"][0])
        self.assertEqual(heartbeat.json()["active_users"][0]["cursor_path"], "/learning_rate")

        state = client.get(
            f"/documents/{self.document['id']}/collaboration-state?since_version=0",
            headers={"X-Actor-Id": self.owner_id},
        )
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json()["checkpoints"][0]["event_type"], "create")
        self.assertEqual(state.json()["checkpoints"][0]["display_name"], "Owner")

        leave = client.delete(
            f"/documents/{self.document['id']}/presence",
            headers={"X-Actor-Id": self.owner_id},
        )
        self.assertEqual(leave.status_code, 200)
        self.assertEqual(leave.json()["active_users"], [])


if __name__ == "__main__":
    unittest.main()
