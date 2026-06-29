from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.audit_service import list_project_audit_log
from app.database import connect, init_db
from app.document_service import assert_replay_matches_latest, create_document, get_history
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import (
    add_project_member,
    create_project,
    create_user,
    create_workspace,
    list_project_members,
    remove_project_member,
    update_project_member,
)


class AuditLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.admin = create_user(self.db_path, email="admin@example.com", display_name="Admin")
        self.editor = create_user(self.db_path, email="editor@example.com", display_name="Editor")
        self.reviewer = create_user(self.db_path, email="reviewer@example.com", display_name="Reviewer")
        self.viewer = create_user(self.db_path, email="viewer@example.com", display_name="Viewer")
        self.outsider = create_user(self.db_path, email="outsider@example.com", display_name="Outsider")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _events(self) -> list[dict]:
        return list_project_audit_log(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )["events"]

    def test_membership_successes_are_audit_logged_and_append_only(self) -> None:
        added = add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
            role="viewer",
        )
        updated = update_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
            role="reviewer",
        )
        removed = remove_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
        )

        events = self._events()
        self.assertEqual([event["action"] for event in events], ["project_member.add", "project_member.update", "project_member.remove"])
        self.assertEqual([event["outcome"] for event in events], ["success", "success", "success"])
        self.assertEqual([event["target_id"] for event in events], [self.viewer["id"], self.viewer["id"], self.viewer["id"]])
        self.assertEqual(events[0]["details"]["member_id"], added["id"])
        self.assertEqual(events[0]["details"]["role"], "viewer")
        self.assertEqual(events[1]["details"]["member_id"], updated["id"])
        self.assertEqual(events[1]["details"]["previous_role"], "viewer")
        self.assertEqual(events[1]["details"]["role"], "reviewer")
        self.assertEqual(events[2]["details"]["removed_member_id"], removed["removed_member_id"])
        self.assertEqual(events[2]["details"]["removed_role"], "reviewer")

        audit_id = events[0]["id"]
        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE audit_log SET action = 'tamper' WHERE id = ?", (audit_id,))
        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM audit_log WHERE id = ?", (audit_id,))

        events_after_tamper_attempts = self._events()
        self.assertEqual([event["action"] for event in events_after_tamper_attempts], [event["action"] for event in events])

    def test_rejected_membership_attempts_are_audit_logged_without_mutation(self) -> None:
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.admin["id"],
            role="admin",
        )
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.editor["id"],
            role="editor",
        )

        with self.assertRaises(AppError) as permission_denied:
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.editor["id"],
                user_id=self.viewer["id"],
                role="viewer",
            )
        self.assertEqual(permission_denied.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as duplicate:
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=self.admin["id"],
                role="admin",
            )
        self.assertEqual(duplicate.exception.code, ErrorCode.PROJECT_MEMBER_ALREADY_EXISTS)

        with self.assertRaises(AppError) as invalid_role:
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=self.viewer["id"],
                role="superuser",
            )
        self.assertEqual(invalid_role.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(AppError) as missing_member:
            remove_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=self.viewer["id"],
            )
        self.assertEqual(missing_member.exception.code, ErrorCode.PROJECT_MEMBER_NOT_FOUND)

        members = list_project_members(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )["members"]
        self.assertEqual({member["user_id"] for member in members}, {self.owner["id"], self.admin["id"], self.editor["id"]})

        failures = [event for event in self._events() if event["outcome"] == "failure"]
        self.assertEqual(
            [(event["action"], event["error_code"]) for event in failures],
            [
                ("project_member.add", ErrorCode.PERMISSION_DENIED),
                ("project_member.add", ErrorCode.PROJECT_MEMBER_ALREADY_EXISTS),
                ("project_member.add", ErrorCode.INVALID_REQUEST),
                ("project_member.remove", ErrorCode.PROJECT_MEMBER_NOT_FOUND),
            ],
        )
        self.assertEqual(failures[0]["actor_id"], self.editor["id"])
        self.assertEqual(failures[0]["target_id"], self.viewer["id"])
        self.assertEqual(failures[2]["details"]["role"], "superuser")

    def test_audit_log_read_is_owner_admin_only(self) -> None:
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.admin["id"],
            role="admin",
        )
        for user, role in ((self.editor, "editor"), (self.reviewer, "reviewer"), (self.viewer, "viewer")):
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=user["id"],
                role=role,
            )

        self.assertGreaterEqual(
            len(list_project_audit_log(self.db_path, project_id=self.project["id"], actor_id=self.owner["id"])["events"]),
            4,
        )
        self.assertGreaterEqual(
            len(list_project_audit_log(self.db_path, project_id=self.project["id"], actor_id=self.admin["id"])["events"]),
            4,
        )

        for actor_id in (self.editor["id"], self.reviewer["id"], self.viewer["id"], self.outsider["id"]):
            with self.assertRaises(AppError) as denied:
                list_project_audit_log(self.db_path, project_id=self.project["id"], actor_id=actor_id)
            self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as missing_actor:
            list_project_audit_log(self.db_path, project_id=self.project["id"], actor_id=None)
        self.assertEqual(missing_actor.exception.code, ErrorCode.AUTH_REQUIRED)

    def test_http_audit_log_route_and_error_envelope(self) -> None:
        client = TestClient(create_app(self.db_path))
        added = client.post(
            f"/projects/{self.project['id']}/members",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"user_id": self.viewer["id"], "role": "viewer"},
        )
        self.assertEqual(added.status_code, 200)

        owner_audit = client.get(
            f"/projects/{self.project['id']}/audit-log",
            headers={"X-Actor-Id": self.owner["id"]},
        )
        self.assertEqual(owner_audit.status_code, 200)
        self.assertEqual(owner_audit.json()["events"][0]["action"], "project_member.add")
        self.assertEqual(owner_audit.json()["events"][0]["outcome"], "success")

        viewer_denied = client.get(
            f"/projects/{self.project['id']}/audit-log",
            headers={"X-Actor-Id": self.viewer["id"]},
        )
        self.assertEqual(viewer_denied.status_code, 403)
        self.assertEqual(viewer_denied.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

        missing_actor = client.get(f"/projects/{self.project['id']}/audit-log")
        self.assertEqual(missing_actor.status_code, 401)
        self.assertEqual(missing_actor.json()["error"]["code"], ErrorCode.AUTH_REQUIRED)

    def test_membership_audit_does_not_create_document_events(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/audit-separation.json",
            content={"value": 1},
        )
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
            role="viewer",
        )
        update_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
            role="reviewer",
        )
        remove_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
        )

        history = get_history(self.db_path, document["id"], actor_id=self.owner["id"])
        self.assertEqual([event["event_type"] for event in history["events"]], ["create"])
        self.assertEqual(len(self._events()), 3)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_audit_log_schema_and_triggers_are_created_idempotently(self) -> None:
        init_db(self.db_path)
        with connect(self.db_path) as conn:
            table = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'audit_log'
                """
            ).fetchone()
            triggers = {
                row["name"]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'trigger' AND tbl_name = 'audit_log'
                    """
                ).fetchall()
            }
            indexes = {
                row["name"]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'index' AND tbl_name = 'audit_log'
                    """
                ).fetchall()
            }

        self.assertIsNotNone(table)
        self.assertIn("trg_audit_log_no_update", triggers)
        self.assertIn("trg_audit_log_no_delete", triggers)
        self.assertIn("idx_audit_log_project_created", indexes)
        self.assertIn("idx_audit_log_actor_created", indexes)


if __name__ == "__main__":
    unittest.main()
