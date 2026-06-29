from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.audit_service import record_audit_event as real_record_audit_event
from app.audit_service import list_project_audit_log
from app.database import connect, init_db
from app.errors import AppError, ErrorCode
from app.workspace_service import (
    add_project_member,
    create_project,
    create_user,
    create_workspace,
    remove_project_member,
    update_project_member,
)


class MembershipAuditAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.admin = create_user(self.db_path, email="admin@example.com", display_name="Admin")
        self.editor = create_user(self.db_path, email="editor@example.com", display_name="Editor")
        self.viewer = create_user(self.db_path, email="viewer@example.com", display_name="Viewer")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _member_role(self, user_id: str) -> str | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT role
                FROM project_members
                WHERE project_id = ? AND user_id = ?
                """,
                (self.project["id"], user_id),
            ).fetchone()
        return row["role"] if row else None

    def _document_event_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]

    def _audit_events(self) -> list[dict]:
        return list_project_audit_log(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )["events"]

    def _fail_success_audit(self, conn, **kwargs):
        if kwargs.get("outcome") == "success":
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "Forced success audit failure.",
                {"forced": True},
            )
        return real_record_audit_event(conn, **kwargs)

    def test_member_add_rolls_back_when_success_audit_write_fails(self) -> None:
        with patch("app.workspace_service.record_audit_event", side_effect=self._fail_success_audit):
            with self.assertRaises(AppError) as raised:
                add_project_member(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    user_id=self.viewer["id"],
                    role="viewer",
                )

        self.assertEqual(raised.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertIsNone(self._member_role(self.viewer["id"]))
        self.assertEqual(self._document_event_count(), 0)
        events = self._audit_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "project_member.add")
        self.assertEqual(events[0]["outcome"], "failure")
        self.assertEqual(events[0]["error_code"], ErrorCode.INTERNAL_ERROR)
        self.assertEqual(events[0]["target_id"], self.viewer["id"])
        self.assertEqual(events[0]["details"]["error_details"], {"forced": True})

    def test_member_update_rolls_back_when_success_audit_write_fails(self) -> None:
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.editor["id"],
            role="editor",
        )

        with patch("app.workspace_service.record_audit_event", side_effect=self._fail_success_audit):
            with self.assertRaises(AppError) as raised:
                update_project_member(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    user_id=self.editor["id"],
                    role="viewer",
                )

        self.assertEqual(raised.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(self._member_role(self.editor["id"]), "editor")
        self.assertEqual(self._document_event_count(), 0)
        failures = [event for event in self._audit_events() if event["outcome"] == "failure"]
        successes = [event for event in self._audit_events() if event["outcome"] == "success"]
        self.assertEqual(len(successes), 1)
        self.assertEqual(successes[0]["action"], "project_member.add")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["action"], "project_member.update")
        self.assertEqual(failures[0]["target_id"], self.editor["id"])
        self.assertEqual(failures[0]["details"]["role"], "viewer")
        self.assertEqual(failures[0]["details"]["error_details"], {"forced": True})

    def test_member_remove_rolls_back_when_success_audit_write_fails(self) -> None:
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.admin["id"],
            role="admin",
        )

        with patch("app.workspace_service.record_audit_event", side_effect=self._fail_success_audit):
            with self.assertRaises(AppError) as raised:
                remove_project_member(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    user_id=self.admin["id"],
                )

        self.assertEqual(raised.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(self._member_role(self.admin["id"]), "admin")
        self.assertEqual(self._document_event_count(), 0)
        failures = [event for event in self._audit_events() if event["outcome"] == "failure"]
        successes = [event for event in self._audit_events() if event["outcome"] == "success"]
        self.assertEqual(len(successes), 1)
        self.assertEqual(successes[0]["action"], "project_member.add")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["action"], "project_member.remove")
        self.assertEqual(failures[0]["target_id"], self.admin["id"])
        self.assertEqual(failures[0]["details"]["error_details"], {"forced": True})


if __name__ == "__main__":
    unittest.main()
