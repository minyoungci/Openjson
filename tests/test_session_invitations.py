from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import init_db
from app.main import create_app


class SessionInvitationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.client = TestClient(create_app(self.db_path))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _signup(self, email: str, name: str) -> dict:
        response = self.client.post(
            "/auth/signup",
            json={"email": email, "display_name": name, "password": "password-123"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_signup_login_me_and_logout_session_token(self) -> None:
        signup = self._signup("owner@example.com", "Owner")
        token = signup["token"]

        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["email"], "owner@example.com")

        login = self.client.post(
            "/auth/login",
            json={"email": "owner@example.com", "password": "password-123"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["token"].startswith("ojs_"))

        logout = self.client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(logout.status_code, 200)

        revoked = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(revoked.status_code, 401)
        self.assertEqual(revoked.json()["error"]["code"], "AUTH_REQUIRED")

    def test_actor_header_fallback_can_be_disabled_for_http_requests(self) -> None:
        with patch.dict(os.environ, {"OPENJSON_ALLOW_ACTOR_HEADER": "0"}, clear=False):
            client = TestClient(create_app(self.db_path))
            signup = client.post(
                "/auth/signup",
                json={"email": "secure@example.com", "display_name": "Secure User", "password": "password-123"},
            )
            self.assertEqual(signup.status_code, 200, signup.text)
            actor_id = signup.json()["user"]["id"]
            token = signup.json()["token"]

            public = client.get("/health", headers={"X-Actor-Id": actor_id})
            self.assertEqual(public.status_code, 200)

            actor_only = client.get("/workspaces", headers={"X-Actor-Id": actor_id})
            self.assertEqual(actor_only.status_code, 401)
            self.assertEqual(actor_only.json()["error"]["code"], "AUTH_REQUIRED")
            self.assertFalse(actor_only.json()["error"]["details"]["actor_header_allowed"])

            bearer = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(bearer.status_code, 200)
            self.assertEqual(bearer.json()["user"]["email"], "secure@example.com")

            mismatch = client.get(
                "/auth/me",
                headers={"Authorization": f"Bearer {token}", "X-Actor-Id": "other_user"},
            )
            self.assertEqual(mismatch.status_code, 403)
            self.assertEqual(mismatch.json()["error"]["code"], "PERMISSION_DENIED")

    def test_project_invitation_accepts_matching_session_user(self) -> None:
        owner = self._signup("owner@example.com", "Owner")
        invited = self._signup("editor@example.com", "Editor")
        owner_headers = {"Authorization": f"Bearer {owner['token']}"}
        editor_headers = {"Authorization": f"Bearer {invited['token']}"}

        workspace = self.client.post("/workspaces", headers=owner_headers, json={"name": "Workspace"})
        self.assertEqual(workspace.status_code, 200)
        project = self.client.post(
            f"/workspaces/{workspace.json()['id']}/projects",
            headers=owner_headers,
            json={"name": "Project"},
        )
        self.assertEqual(project.status_code, 200)
        project_id = project.json()["id"]

        invitation = self.client.post(
            f"/projects/{project_id}/invitations",
            headers=owner_headers,
            json={"email": "editor@example.com", "role": "editor"},
        )
        self.assertEqual(invitation.status_code, 200)
        self.assertTrue(invitation.json()["token"].startswith("oji_"))

        accepted = self.client.post(
            "/invitations/accept",
            headers=editor_headers,
            json={"token": invitation.json()["token"]},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["member"]["role"], "editor")

        members = self.client.get(f"/projects/{project_id}/members", headers=editor_headers)
        self.assertEqual(members.status_code, 200)
        self.assertEqual(
            {member["email"]: member["role"] for member in members.json()["members"]},
            {"owner@example.com": "owner", "editor@example.com": "editor"},
        )

    def test_invitation_rejects_wrong_email_user(self) -> None:
        owner = self._signup("owner@example.com", "Owner")
        wrong = self._signup("wrong@example.com", "Wrong User")
        owner_headers = {"Authorization": f"Bearer {owner['token']}"}
        wrong_headers = {"Authorization": f"Bearer {wrong['token']}"}
        workspace = self.client.post("/workspaces", headers=owner_headers, json={"name": "Workspace"}).json()
        project = self.client.post(
            f"/workspaces/{workspace['id']}/projects",
            headers=owner_headers,
            json={"name": "Project"},
        ).json()
        invitation = self.client.post(
            f"/projects/{project['id']}/invitations",
            headers=owner_headers,
            json={"email": "editor@example.com", "role": "editor"},
        ).json()

        accepted = self.client.post(
            "/invitations/accept",
            headers=wrong_headers,
            json={"token": invitation["token"]},
        )

        self.assertEqual(accepted.status_code, 403)
        self.assertEqual(accepted.json()["error"]["code"], "PERMISSION_DENIED")


if __name__ == "__main__":
    unittest.main()
