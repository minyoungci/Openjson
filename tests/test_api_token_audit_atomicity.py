from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.audit_service import list_project_audit_log
from app.audit_service import record_audit_event as real_record_audit_event
from app.auth_service import create_project_api_token, revoke_project_api_token
from app.database import connect, init_db
from app.errors import AppError, ErrorCode
from app.workspace_service import create_project, create_user, create_workspace


class ApiTokenAuditAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _audit_events(self) -> list[dict]:
        return list_project_audit_log(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )["events"]

    def _document_event_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]

    def _token_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM api_tokens").fetchone()["count"]

    def _token_revoked_at(self, token_id: str) -> str | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT revoked_at FROM api_tokens WHERE id = ?", (token_id,)).fetchone()
        return row["revoked_at"] if row else None

    def _fail_success_audit(self, conn, **kwargs):
        if kwargs.get("outcome") == "success":
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "Forced success audit failure.",
                {"forced": True},
            )
        return real_record_audit_event(conn, **kwargs)

    def test_token_create_rolls_back_when_success_audit_write_fails(self) -> None:
        with patch("app.auth_service.record_audit_event", side_effect=self._fail_success_audit):
            with self.assertRaises(AppError) as raised:
                create_project_api_token(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.owner["id"],
                    name="forced token",
                )

        self.assertEqual(raised.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(self._token_count(), 0)
        self.assertEqual(self._document_event_count(), 0)

        events = self._audit_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "api_token.create")
        self.assertEqual(events[0]["outcome"], "failure")
        self.assertEqual(events[0]["error_code"], ErrorCode.INTERNAL_ERROR)
        self.assertEqual(events[0]["target_type"], "api_token")
        self.assertEqual(events[0]["details"]["name"], "forced token")
        self.assertEqual(events[0]["details"]["error_details"], {"forced": True})
        self.assertNotIn("token_hash", events[0]["details"])

    def test_token_revoke_rolls_back_when_success_audit_write_fails(self) -> None:
        created = create_project_api_token(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name="ci token",
        )

        with patch("app.auth_service.record_audit_event", side_effect=self._fail_success_audit):
            with self.assertRaises(AppError) as raised:
                revoke_project_api_token(
                    self.db_path,
                    project_id=self.project["id"],
                    token_id=created["id"],
                    actor_id=self.owner["id"],
                )

        self.assertEqual(raised.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertIsNone(self._token_revoked_at(created["id"]))
        self.assertEqual(self._document_event_count(), 0)

        events = self._audit_events()
        successes = [event for event in events if event["outcome"] == "success"]
        failures = [event for event in events if event["outcome"] == "failure"]
        self.assertEqual([(event["action"], event["target_id"]) for event in successes], [("api_token.create", created["id"])])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["action"], "api_token.revoke")
        self.assertEqual(failures[0]["target_id"], created["id"])
        self.assertEqual(failures[0]["details"]["token_prefix"], created["token_prefix"])
        self.assertEqual(failures[0]["details"]["error_details"], {"forced": True})
        self.assertNotIn(created["token"], json.dumps(failures[0]["details"], sort_keys=True))


if __name__ == "__main__":
    unittest.main()
