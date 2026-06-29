from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.comment_service import create_comment_thread, list_comment_threads
from app.document_service import assert_replay_matches_latest, create_document, get_document, get_history, patch_document
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.review_service import create_review_request, list_project_review_requests
from app.schema_service import create_schema, list_project_schemas
from app.workspace_service import (
    add_project_member,
    create_project,
    create_user,
    create_workspace,
    get_project,
    list_project_members,
    remove_project_member,
    update_project_member,
)


class ProjectMembershipTests(unittest.TestCase):
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

    def _add_default_members(self) -> None:
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
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
            role="viewer",
        )

    def test_members_can_list_and_nonmembers_are_denied(self) -> None:
        self._add_default_members()

        owner_members = list_project_members(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        viewer_members = list_project_members(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
        )
        self.assertEqual([member["role"] for member in owner_members["members"]], ["owner", "admin", "editor", "viewer"])
        self.assertEqual([member["user_id"] for member in viewer_members["members"]], [member["user_id"] for member in owner_members["members"]])

        with self.assertRaises(AppError) as denied:
            list_project_members(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.outsider["id"],
            )
        self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_owner_and_admin_can_manage_members_but_editor_cannot(self) -> None:
        admin_member = add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.admin["id"],
            role="admin",
        )
        self.assertEqual(admin_member["role"], "admin")

        reviewer_member = add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.admin["id"],
            user_id=self.reviewer["id"],
            role="reviewer",
        )
        self.assertEqual(reviewer_member["role"], "reviewer")

        updated = update_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.admin["id"],
            user_id=self.reviewer["id"],
            role="viewer",
        )
        self.assertEqual(updated["role"], "viewer")

        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.admin["id"],
            user_id=self.editor["id"],
            role="editor",
        )
        with self.assertRaises(AppError) as editor_denied:
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.editor["id"],
                user_id=self.viewer["id"],
                role="viewer",
            )
        self.assertEqual(editor_denied.exception.code, ErrorCode.PERMISSION_DENIED)

        removed = remove_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.admin["id"],
            user_id=self.reviewer["id"],
        )
        self.assertEqual(removed["removed_user_id"], self.reviewer["id"])

    def test_duplicate_missing_user_invalid_role_and_missing_member_errors(self) -> None:
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
            role="viewer",
        )

        with self.assertRaises(AppError) as duplicate:
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=self.viewer["id"],
                role="viewer",
            )
        self.assertEqual(duplicate.exception.code, ErrorCode.PROJECT_MEMBER_ALREADY_EXISTS)

        with self.assertRaises(AppError) as missing_user:
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id="missing_user",
                role="viewer",
            )
        self.assertEqual(missing_user.exception.code, ErrorCode.USER_NOT_FOUND)

        with self.assertRaises(AppError) as invalid_role:
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=self.reviewer["id"],
                role="superuser",
            )
        self.assertEqual(invalid_role.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(AppError) as missing_member:
            update_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=self.reviewer["id"],
                role="viewer",
            )
        self.assertEqual(missing_member.exception.code, ErrorCode.PROJECT_MEMBER_NOT_FOUND)

    def test_last_owner_cannot_be_demoted_or_removed_but_non_last_owner_can(self) -> None:
        with self.assertRaises(AppError) as demote_last_owner:
            update_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=self.owner["id"],
                role="admin",
            )
        self.assertEqual(demote_last_owner.exception.code, ErrorCode.INVALID_REQUEST)

        with self.assertRaises(AppError) as remove_last_owner:
            remove_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=self.owner["id"],
            )
        self.assertEqual(remove_last_owner.exception.code, ErrorCode.INVALID_REQUEST)

        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.admin["id"],
            role="owner",
        )
        demoted = update_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.admin["id"],
            user_id=self.owner["id"],
            role="admin",
        )
        self.assertEqual(demoted["role"], "admin")
        removed = remove_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.admin["id"],
            user_id=self.owner["id"],
        )
        self.assertEqual(removed["removed_user_id"], self.owner["id"])

    def test_db_triggers_reject_direct_sql_last_owner_removal_or_demotion(self) -> None:
        with connect(self.db_path) as conn:
            member_id = conn.execute(
                """
                SELECT id
                FROM project_members
                WHERE project_id = ? AND user_id = ?
                """,
                (self.project["id"], self.owner["id"]),
            ).fetchone()["id"]

        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE project_members SET role = 'admin' WHERE id = ?", (member_id,))

        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM project_members WHERE id = ?", (member_id,))

        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.admin["id"],
            role="owner",
        )
        with connect(self.db_path) as conn:
            conn.execute("UPDATE project_members SET role = 'admin' WHERE id = ?", (member_id,))
        with connect(self.db_path) as conn:
            role = conn.execute("SELECT role FROM project_members WHERE id = ?", (member_id,)).fetchone()["role"]
        self.assertEqual(role, "admin")

    def test_removed_member_loses_project_scoped_access_immediately(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/revoke.json",
            content={"value": 1},
        )
        create_schema(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name="config",
            version="1.0.0",
            schema_json={"type": "object"},
        )
        create_comment_thread(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            body="Owner note",
        )
        create_review_request(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            title="No-op value proposal",
            description=None,
            changes=[
                {
                    "document_id": document["id"],
                    "base_version": 1,
                    "patch": [{"op": "replace", "path": "/value", "value": 2}],
                }
            ],
        )
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
            role="viewer",
        )

        self.assertEqual(get_project(self.db_path, project_id=self.project["id"], actor_id=self.viewer["id"])["role"], "viewer")
        self.assertEqual(get_document(self.db_path, document["id"], actor_id=self.viewer["id"])["id"], document["id"])
        self.assertEqual(len(list_comment_threads(self.db_path, document_id=document["id"], actor_id=self.viewer["id"])["threads"]), 1)
        self.assertEqual(len(list_project_schemas(self.db_path, self.project["id"], actor_id=self.viewer["id"])["schemas"]), 1)
        self.assertEqual(
            len(
                list_project_review_requests(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=self.viewer["id"],
                )["review_requests"]
            ),
            1,
        )

        remove_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
        )

        for action in (
            lambda: get_project(self.db_path, project_id=self.project["id"], actor_id=self.viewer["id"]),
            lambda: list_project_members(self.db_path, project_id=self.project["id"], actor_id=self.viewer["id"]),
            lambda: get_document(self.db_path, document["id"], actor_id=self.viewer["id"]),
            lambda: get_history(self.db_path, document["id"], actor_id=self.viewer["id"]),
            lambda: list_comment_threads(self.db_path, document_id=document["id"], actor_id=self.viewer["id"]),
            lambda: list_project_schemas(self.db_path, self.project["id"], actor_id=self.viewer["id"]),
            lambda: list_project_review_requests(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.viewer["id"],
            ),
        ):
            with self.assertRaises(AppError) as denied:
                action()
            self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_role_update_immediately_changes_document_permissions(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/role-change.json",
            content={"value": 1},
        )
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.editor["id"],
            role="editor",
        )

        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.editor["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
        )
        update_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.editor["id"],
            role="viewer",
        )

        self.assertEqual(get_document(self.db_path, document["id"], actor_id=self.editor["id"])["content"], {"value": 2})
        with self.assertRaises(AppError) as denied_write:
            patch_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.editor["id"],
                base_version=2,
                patch=[{"op": "replace", "path": "/value", "value": 3}],
            )
        self.assertEqual(denied_write.exception.code, ErrorCode.PERMISSION_DENIED)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_membership_changes_do_not_create_document_events(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/member-audit.json",
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
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_http_membership_routes_and_error_envelope(self) -> None:
        client = TestClient(create_app(self.db_path))

        missing_actor = client.get(f"/projects/{self.project['id']}/members")
        self.assertEqual(missing_actor.status_code, 401)
        self.assertEqual(missing_actor.json()["error"]["code"], ErrorCode.AUTH_REQUIRED)

        added = client.post(
            f"/projects/{self.project['id']}/members",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"user_id": self.viewer["id"], "role": "viewer"},
        )
        self.assertEqual(added.status_code, 200)
        self.assertEqual(added.json()["role"], "viewer")

        duplicate = client.post(
            f"/projects/{self.project['id']}/members",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"user_id": self.viewer["id"], "role": "viewer"},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], ErrorCode.PROJECT_MEMBER_ALREADY_EXISTS)

        updated = client.patch(
            f"/projects/{self.project['id']}/members/{self.viewer['id']}",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"role": "reviewer"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["role"], "reviewer")

        members = client.get(
            f"/projects/{self.project['id']}/members",
            headers={"X-Actor-Id": self.viewer["id"]},
        )
        self.assertEqual(members.status_code, 200)
        self.assertEqual(len(members.json()["members"]), 2)

        removed = client.delete(
            f"/projects/{self.project['id']}/members/{self.viewer['id']}",
            headers={"X-Actor-Id": self.owner["id"]},
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["removed_user_id"], self.viewer["id"])

    def test_http_membership_malformed_and_missing_member_errors(self) -> None:
        client = TestClient(create_app(self.db_path))

        malformed = client.post(
            f"/projects/{self.project['id']}/members",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"user_id": self.viewer["id"]},
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()["error"]["code"], ErrorCode.INVALID_JSON_SYNTAX)

        missing_update = client.patch(
            f"/projects/{self.project['id']}/members/{self.viewer['id']}",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"role": "viewer"},
        )
        self.assertEqual(missing_update.status_code, 404)
        self.assertEqual(missing_update.json()["error"]["code"], ErrorCode.PROJECT_MEMBER_NOT_FOUND)

        missing_delete = client.delete(
            f"/projects/{self.project['id']}/members/{self.viewer['id']}",
            headers={"X-Actor-Id": self.owner["id"]},
        )
        self.assertEqual(missing_delete.status_code, 404)
        self.assertEqual(missing_delete.json()["error"]["code"], ErrorCode.PROJECT_MEMBER_NOT_FOUND)

    def test_project_membership_routes_are_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/members", "GET"), routes)
        self.assertIn(("/projects/{project_id}/members", "POST"), routes)
        self.assertIn(("/projects/{project_id}/members/{user_id}", "PATCH"), routes)
        self.assertIn(("/projects/{project_id}/members/{user_id}", "DELETE"), routes)


if __name__ == "__main__":
    unittest.main()
