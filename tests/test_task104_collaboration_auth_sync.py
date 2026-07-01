from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.main import create_app


class Task104CollaborationAuthSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.previous_email_backend = os.environ.get("OPENJSON_EMAIL_BACKEND")
        os.environ["OPENJSON_EMAIL_BACKEND"] = "console"
        self.client = TestClient(create_app(self.db_path))

    def tearDown(self) -> None:
        if self.previous_email_backend is None:
            os.environ.pop("OPENJSON_EMAIL_BACKEND", None)
        else:
            os.environ["OPENJSON_EMAIL_BACKEND"] = self.previous_email_backend
        self.tmp.cleanup()

    def _signup(self, email: str, name: str) -> dict:
        response = self.client.post(
            "/auth/signup",
            json={"email": email, "display_name": name, "password": "password-123"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _project(self) -> tuple[dict, dict, dict]:
        owner = self._signup("owner@example.com", "Owner")
        headers = {"Authorization": f"Bearer {owner['token']}"}
        workspace = self.client.post("/workspaces", headers=headers, json={"name": "Workspace"})
        self.assertEqual(workspace.status_code, 200, workspace.text)
        project = self.client.post(
            f"/workspaces/{workspace.json()['id']}/projects",
            headers=headers,
            json={"name": "Project"},
        )
        self.assertEqual(project.status_code, 200, project.text)
        return owner, workspace.json(), project.json()

    def test_refresh_token_rotates_and_reuse_is_rejected(self) -> None:
        signup = self._signup("refresh@example.com", "Refresh User")
        old_access = signup["token"]
        old_refresh = signup["refresh_token"]

        refreshed = self.client.post("/auth/refresh", json={"refresh_token": old_refresh})
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertNotEqual(refreshed.json()["token"], old_access)
        self.assertNotEqual(refreshed.json()["refresh_token"], old_refresh)

        old_me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {old_access}"})
        self.assertEqual(old_me.status_code, 401)

        new_me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {refreshed.json()['token']}"})
        self.assertEqual(new_me.status_code, 200)

        reused = self.client.post("/auth/refresh", json={"refresh_token": old_refresh})
        self.assertEqual(reused.status_code, 401)
        self.assertEqual(reused.json()["error"]["code"], "AUTH_REQUIRED")

    def test_invitation_creation_records_email_delivery(self) -> None:
        owner, _, project = self._project()
        response = self.client.post(
            f"/projects/{project['id']}/invitations",
            headers={"Authorization": f"Bearer {owner['token']}"},
            json={"email": "invitee@example.com", "role": "editor"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        delivery = response.json()["email_delivery"]
        self.assertEqual(delivery["status"], "sent")
        self.assertEqual(delivery["delivery_backend"], "console")
        self.assertTrue(delivery["accept_url"].endswith(response.json()["token"]))
        with connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) AS count FROM email_deliveries").fetchone()["count"]
        self.assertEqual(count, 1)

    def test_invitation_creation_sends_smtp_email_when_configured(self) -> None:
        owner, _, project = self._project()
        smtp_env = {
            "OPENJSON_EMAIL_BACKEND": "smtp",
            "OPENJSON_PUBLIC_BASE_URL": "https://openjson.example.test",
            "OPENJSON_EMAIL_FROM": "no-reply@openjson.example.test",
            "OPENJSON_SMTP_HOST": "smtp.example.test",
            "OPENJSON_SMTP_PORT": "2525",
            "OPENJSON_SMTP_USERNAME": "smtp-user",
            "OPENJSON_SMTP_PASSWORD": "smtp-pass",
            "OPENJSON_SMTP_TLS": "1",
        }
        with patch.dict(os.environ, smtp_env, clear=False), patch("app.email_service.smtplib.SMTP") as smtp_cls:
            smtp = smtp_cls.return_value.__enter__.return_value
            response = self.client.post(
                f"/projects/{project['id']}/invitations",
                headers={"Authorization": f"Bearer {owner['token']}"},
                json={"email": "smtp-invitee@example.com", "role": "viewer"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        delivery = response.json()["email_delivery"]
        self.assertEqual(delivery["status"], "sent")
        self.assertEqual(delivery["delivery_backend"], "smtp")
        self.assertIsNone(delivery["accept_url"])
        smtp_cls.assert_called_once_with("smtp.example.test", 2525, timeout=10)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("smtp-user", "smtp-pass")
        self.assertEqual(smtp.send_message.call_count, 1)
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "smtp-invitee@example.com")
        self.assertEqual(message["From"], "no-reply@openjson.example.test")
        self.assertIn(response.json()["token"], message.get_content())
        self.assertIn("https://openjson.example.test/app?invite_token=", message.get_content())

    def test_invitation_creation_records_smtp_failure_without_rolling_back_invite(self) -> None:
        owner, _, project = self._project()
        smtp_env = {
            "OPENJSON_EMAIL_BACKEND": "smtp",
            "OPENJSON_PUBLIC_BASE_URL": "https://openjson.example.test",
        }
        with patch.dict(os.environ, smtp_env, clear=False):
            response = self.client.post(
                f"/projects/{project['id']}/invitations",
                headers={"Authorization": f"Bearer {owner['token']}"},
                json={"email": "missing-smtp@example.com", "role": "editor"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["token"].startswith("oji_"))
        self.assertEqual(body["email_delivery"]["status"], "failed")
        self.assertIn("OPENJSON_SMTP_HOST is required", body["email_delivery"]["error_message"])
        with connect(self.db_path) as conn:
            invitation_count = conn.execute("SELECT COUNT(*) AS count FROM project_invitations").fetchone()["count"]
            delivery_count = conn.execute("SELECT COUNT(*) AS count FROM email_deliveries").fetchone()["count"]
        self.assertEqual(invitation_count, 1)
        self.assertEqual(delivery_count, 1)

    def test_offline_sync_applies_idempotently_and_reports_conflict(self) -> None:
        owner, _, project = self._project()
        headers = {"Authorization": f"Bearer {owner['token']}"}
        document = self.client.post(
            f"/projects/{project['id']}/documents",
            headers=headers,
            json={"full_path": "offline/doc.json", "content": {"a": 1, "b": 1}},
        ).json()

        first = self.client.post(
            f"/projects/{project['id']}/offline-sync",
            headers=headers,
            json={
                "items": [
                    {
                        "client_operation_id": "op-1",
                        "document_id": document["id"],
                        "base_version": 1,
                        "content_text": "{\"a\":2,\"b\":1}",
                    }
                ]
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["summary"], {"applied": 1, "conflict": 0, "failed": 0})
        self.assertEqual(first.json()["results"][0]["status"], "applied")

        replay = self.client.post(
            f"/projects/{project['id']}/offline-sync",
            headers=headers,
            json={
                "items": [
                    {
                        "client_operation_id": "op-1",
                        "document_id": document["id"],
                        "base_version": 1,
                        "content_text": "{\"a\":2,\"b\":1}",
                    }
                ]
            },
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["results"][0]["idempotent_replay"])

        conflict = self.client.post(
            f"/projects/{project['id']}/offline-sync",
            headers=headers,
            json={
                "items": [
                    {
                        "client_operation_id": "op-conflict",
                        "document_id": document["id"],
                        "base_version": 1,
                        "content_text": "{\"a\":3,\"b\":1}",
                    }
                ]
            },
        )
        self.assertEqual(conflict.status_code, 200, conflict.text)
        self.assertEqual(conflict.json()["summary"], {"applied": 0, "conflict": 1, "failed": 0})

    def test_websocket_text_session_commits_as_document_event(self) -> None:
        owner, _, project = self._project()
        headers = {"Authorization": f"Bearer {owner['token']}"}
        document = self.client.post(
            f"/projects/{project['id']}/documents",
            headers=headers,
            json={"full_path": "live/doc.json", "content": {"a": 1}},
        ).json()

        with self.client.websocket_connect(
            f"/ws/documents/{document['id']}/collaboration?token={owner['token']}"
        ) as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "text_session.join"})
            state = websocket.receive_json()
            self.assertEqual(state["type"], "text_session.state")
            index = state["content_text"].index("1")
            websocket.send_json(
                {
                    "type": "text_session.op",
                    "client_id": "test-client",
                    "base_text_revision": state["text_revision"],
                    "op": {"type": "replace", "index": index, "length": 1, "text": "2"},
                }
            )
            accepted = websocket.receive_json()
            self.assertEqual(accepted["type"], "text_session.op.accepted")
            websocket.send_json({"type": "text_session.commit", "text_revision": accepted["server_text_revision"]})
            committed = websocket.receive_json()
            self.assertEqual(committed["type"], "text_session.committed")
            self.assertEqual(committed["result_version"], 2)

        loaded = self.client.get(f"/documents/{document['id']}", headers=headers)
        self.assertEqual(loaded.json()["content"], {"a": 2})
        history = self.client.get(f"/documents/{document['id']}/history", headers=headers)
        self.assertEqual([event["event_type"] for event in history.json()["events"]], ["create", "update"])


if __name__ == "__main__":
    unittest.main()
