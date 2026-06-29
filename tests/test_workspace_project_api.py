from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db, utc_now
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import (
    create_project,
    create_user,
    create_workspace,
    get_project,
    get_workspace,
    list_workspace_projects,
    list_workspaces,
)


class WorkspaceProjectApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_user(self, email: str = "owner@example.com", display_name: str = "Owner") -> dict:
        return create_user(self.db_path, email=email, display_name=display_name)

    def test_create_user_workspace_project_and_owner_membership(self) -> None:
        user = self._create_user()
        workspace = create_workspace(self.db_path, actor_id=user["id"], name="Workspace")
        project = create_project(
            self.db_path,
            workspace_id=workspace["id"],
            actor_id=user["id"],
            name="Project",
            description="Project description",
        )

        self.assertEqual(workspace["owner_id"], user["id"])
        self.assertEqual(project["workspace_id"], workspace["id"])
        self.assertEqual(project["role"], "owner")
        loaded_project = get_project(self.db_path, project_id=project["id"], actor_id=user["id"])
        self.assertEqual(loaded_project["id"], project["id"])
        self.assertEqual(loaded_project["role"], "owner")
        with connect(self.db_path) as conn:
            member = conn.execute(
                """
                SELECT role
                FROM project_members
                WHERE project_id = ? AND user_id = ?
                """,
                (project["id"], user["id"]),
            ).fetchone()
            self.assertEqual(member["role"], "owner")

    def test_duplicate_email_and_invalid_create_requests_are_rejected(self) -> None:
        self._create_user(email="duplicate@example.com")

        with self.assertRaises(AppError) as duplicate:
            self._create_user(email="Duplicate@Example.com")
        self.assertEqual(duplicate.exception.code, ErrorCode.USER_ALREADY_EXISTS)

        with self.assertRaises(AppError) as invalid_email:
            create_user(self.db_path, email="not-an-email", display_name="Invalid")
        self.assertEqual(invalid_email.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(AppError) as missing_actor:
            create_workspace(self.db_path, actor_id=None, name="No Actor")
        self.assertEqual(missing_actor.exception.code, ErrorCode.AUTH_REQUIRED)

    def test_workspace_lists_include_owned_and_project_member_workspaces(self) -> None:
        owner = self._create_user()
        member = self._create_user(email="member@example.com", display_name="Member")
        outsider = self._create_user(email="outsider@example.com", display_name="Outsider")
        workspace = create_workspace(self.db_path, actor_id=owner["id"], name="Shared Workspace")
        project = create_project(
            self.db_path,
            workspace_id=workspace["id"],
            actor_id=owner["id"],
            name="Visible Project",
        )
        now = utc_now()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO project_members (id, project_id, user_id, role, created_at)
                VALUES (?, ?, ?, 'viewer', ?)
                """,
                ("member_viewer", project["id"], member["id"], now),
            )

        owner_workspaces = list_workspaces(self.db_path, actor_id=owner["id"])["workspaces"]
        member_workspaces = list_workspaces(self.db_path, actor_id=member["id"])["workspaces"]
        outsider_workspaces = list_workspaces(self.db_path, actor_id=outsider["id"])["workspaces"]

        self.assertEqual([row["id"] for row in owner_workspaces], [workspace["id"]])
        self.assertEqual([row["id"] for row in member_workspaces], [workspace["id"]])
        self.assertEqual(outsider_workspaces, [])
        self.assertEqual(get_workspace(self.db_path, workspace_id=workspace["id"], actor_id=member["id"])["id"], workspace["id"])

        member_projects = list_workspace_projects(
            self.db_path,
            workspace_id=workspace["id"],
            actor_id=member["id"],
        )
        self.assertEqual(member_projects["projects"][0]["id"], project["id"])
        self.assertEqual(member_projects["projects"][0]["role"], "viewer")

        with self.assertRaises(AppError) as denied:
            create_project(
                self.db_path,
                workspace_id=workspace["id"],
                actor_id=member["id"],
                name="Denied Project",
            )
        self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_project_read_requires_project_membership(self) -> None:
        owner = self._create_user()
        outsider = self._create_user(email="outsider@example.com", display_name="Outsider")
        workspace = create_workspace(self.db_path, actor_id=owner["id"], name="Workspace")
        project = create_project(self.db_path, workspace_id=workspace["id"], actor_id=owner["id"], name="Project")

        with self.assertRaises(AppError) as denied:
            get_project(self.db_path, project_id=project["id"], actor_id=outsider["id"])
        self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as missing:
            get_project(self.db_path, project_id="missing_project", actor_id=owner["id"])
        self.assertEqual(missing.exception.code, ErrorCode.PROJECT_NOT_FOUND)

    def test_workspace_project_routes_are_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/users", "POST"), routes)
        self.assertIn(("/workspaces", "POST"), routes)
        self.assertIn(("/workspaces", "GET"), routes)
        self.assertIn(("/workspaces/{workspace_id}", "GET"), routes)
        self.assertIn(("/workspaces/{workspace_id}/projects", "POST"), routes)
        self.assertIn(("/workspaces/{workspace_id}/projects", "GET"), routes)
        self.assertIn(("/projects/{project_id}", "GET"), routes)

    def test_http_bootstrap_flow_and_error_envelope(self) -> None:
        client = TestClient(create_app(self.db_path))

        user_response = client.post("/users", json={"email": "api@example.com", "display_name": "API User"})
        self.assertEqual(user_response.status_code, 200)
        actor_id = user_response.json()["id"]

        missing_actor = client.post("/workspaces", json={"name": "No Actor"})
        self.assertEqual(missing_actor.status_code, 401)
        self.assertEqual(missing_actor.json()["error"]["code"], ErrorCode.AUTH_REQUIRED)

        malformed = client.post("/users", json={"email": "missing-display-name@example.com"})
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()["error"]["code"], ErrorCode.INVALID_JSON_SYNTAX)

        duplicate = client.post("/users", json={"email": "API@Example.com", "display_name": "Duplicate"})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], ErrorCode.USER_ALREADY_EXISTS)

        workspace_response = client.post(
            "/workspaces",
            headers={"X-Actor-Id": actor_id},
            json={"name": "API Workspace"},
        )
        self.assertEqual(workspace_response.status_code, 200)
        workspace_id = workspace_response.json()["id"]

        project_response = client.post(
            f"/workspaces/{workspace_id}/projects",
            headers={"X-Actor-Id": actor_id},
            json={"name": "API Project"},
        )
        self.assertEqual(project_response.status_code, 200)
        project_id = project_response.json()["id"]

        unauthenticated_project = client.get(f"/projects/{project_id}")
        self.assertEqual(unauthenticated_project.status_code, 401)
        self.assertEqual(unauthenticated_project.json()["error"]["code"], ErrorCode.AUTH_REQUIRED)

        project_get = client.get(f"/projects/{project_id}", headers={"X-Actor-Id": actor_id})
        self.assertEqual(project_get.status_code, 200)
        self.assertEqual(project_get.json()["role"], "owner")

    def test_project_create_rolls_back_when_owner_membership_insert_fails(self) -> None:
        user = self._create_user()
        workspace = create_workspace(self.db_path, actor_id=user["id"], name="Workspace")
        with connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TRIGGER fail_project_owner_membership
                BEFORE INSERT ON project_members
                BEGIN
                    SELECT RAISE(ABORT, 'forced project member failure');
                END;
                """
            )

        with self.assertRaises(sqlite3.IntegrityError):
            create_project(
                self.db_path,
                workspace_id=workspace["id"],
                actor_id=user["id"],
                name="Rolled Back Project",
            )

        with connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM projects").fetchone()["count"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS count FROM project_members").fetchone()["count"], 0)


if __name__ == "__main__":
    unittest.main()
