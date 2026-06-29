from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.database import connect, init_db, utc_now
from app.document_service import (
    assert_replay_matches_latest,
    create_document,
    diff_document_versions,
    get_document,
    get_history,
    patch_document,
    preview_document_patch,
    rollback_document,
    validate_document,
)
from app.errors import AppError, ErrorCode
from app.schema_service import create_schema, get_schema, list_project_schemas


class ProjectRbacTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.workspace_id = "workspace_rbac"
        self.project_id = "project_rbac"
        self.users = {
            "owner": "user_owner",
            "admin": "user_admin",
            "editor": "user_editor",
            "reviewer": "user_reviewer",
            "viewer": "user_viewer",
            "nonmember": "user_nonmember",
        }
        now = utc_now()
        with connect(self.db_path) as conn:
            for label, user_id in self.users.items():
                conn.execute(
                    "INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, f"{label}@example.com", label.title(), now, now),
                )
            conn.execute(
                "INSERT INTO workspaces (id, name, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (self.workspace_id, "RBAC Workspace", self.users["owner"], now, now),
            )
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (self.project_id, self.workspace_id, "RBAC Project", None, now, now),
            )
            for role in ("owner", "admin", "editor", "reviewer", "viewer"):
                conn.execute(
                    "INSERT INTO project_members (id, project_id, user_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (f"member_{role}", self.project_id, self.users[role], role, now),
                )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_document(self) -> dict:
        return create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.users["owner"],
            full_path="config/rbac.json",
            content={"value": 1},
        )

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _snapshot(self, document_id: str) -> dict:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT current_snapshot_json FROM json_documents WHERE id = ?", (document_id,)).fetchone()
            return json.loads(row["current_snapshot_json"])

    def _document_version(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT current_version FROM json_documents WHERE id = ?", (document_id,)).fetchone()
            return row["current_version"]

    def test_missing_actor_and_nonmember_are_denied(self) -> None:
        document = self._create_document()

        with self.assertRaises(AppError) as missing_actor:
            get_document(self.db_path, document["id"], actor_id=None)
        self.assertEqual(missing_actor.exception.code, ErrorCode.AUTH_REQUIRED)

        with self.assertRaises(AppError) as nonmember_read:
            get_document(self.db_path, document["id"], actor_id=self.users["nonmember"])
        self.assertEqual(nonmember_read.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as nonmember_create:
            create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.users["nonmember"],
                full_path="config/nonmember.json",
                content={"value": 1},
            )
        self.assertEqual(nonmember_create.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_viewer_can_read_but_cannot_mutate_or_validate(self) -> None:
        document = self._create_document()

        loaded = get_document(self.db_path, document["id"], actor_id=self.users["viewer"])
        self.assertEqual(loaded["content"], {"value": 1})
        self.assertEqual(len(get_history(self.db_path, document["id"], actor_id=self.users["viewer"])["events"]), 1)

        with self.assertRaises(AppError) as denied_patch:
            patch_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.users["viewer"],
                base_version=1,
                patch=[{"op": "replace", "path": "/value", "value": 2}],
            )
        self.assertEqual(denied_patch.exception.code, ErrorCode.PERMISSION_DENIED)
        self.assertEqual(self._event_count(document["id"]), 1)
        self.assertEqual(self._snapshot(document["id"]), {"value": 1})

        with self.assertRaises(AppError) as denied_validate:
            validate_document(self.db_path, document["id"], actor_id=self.users["viewer"])
        self.assertEqual(denied_validate.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_patch_preview_requires_write_permission_without_mutation(self) -> None:
        document = self._create_document()

        preview = preview_document_patch(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["editor"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
        )

        self.assertFalse(preview["persisted"])
        self.assertEqual(preview["candidate_content"], {"value": 2})
        self.assertEqual(preview["changed_paths"], ["/value"])
        self.assertEqual(self._event_count(document["id"]), 1)
        self.assertEqual(self._document_version(document["id"]), 1)
        self.assertEqual(self._snapshot(document["id"]), {"value": 1})

        for role in ("reviewer", "viewer", "nonmember"):
            with self.subTest(role=role):
                with self.assertRaises(AppError) as denied_preview:
                    preview_document_patch(
                        self.db_path,
                        document_id=document["id"],
                        actor_id=self.users[role],
                        base_version=1,
                        patch=[{"op": "replace", "path": "/value", "value": 3}],
                    )
                self.assertEqual(denied_preview.exception.code, ErrorCode.PERMISSION_DENIED)
                self.assertEqual(self._event_count(document["id"]), 1)
                self.assertEqual(self._document_version(document["id"]), 1)
                self.assertEqual(self._snapshot(document["id"]), {"value": 1})

    def test_reviewer_can_read_diff_and_validate_but_cannot_mutate(self) -> None:
        document = self._create_document()
        patched = patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["editor"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
        )

        self.assertEqual(patched["current_version"], 2)
        self.assertEqual(get_document(self.db_path, document["id"], actor_id=self.users["reviewer"])["content"], {"value": 2})
        self.assertTrue(validate_document(self.db_path, document["id"], actor_id=self.users["reviewer"])["valid"])
        diff = diff_document_versions(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["reviewer"],
            from_version=1,
            to_version=2,
        )
        self.assertEqual(diff["changes"][0]["path"], "/value")

        with self.assertRaises(AppError) as denied_patch:
            patch_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.users["reviewer"],
                base_version=2,
                patch=[{"op": "replace", "path": "/value", "value": 3}],
            )
        self.assertEqual(denied_patch.exception.code, ErrorCode.PERMISSION_DENIED)
        self.assertEqual(self._event_count(document["id"]), 2)

    def test_editor_can_patch_rollback_and_validate_but_cannot_create_schema(self) -> None:
        document = self._create_document()
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["editor"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
        )
        rolled_back = rollback_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["editor"],
            base_version=2,
            target_version=1,
        )

        self.assertEqual(rolled_back["current_version"], 3)
        self.assertTrue(validate_document(self.db_path, document["id"], actor_id=self.users["editor"])["valid"])
        assert_replay_matches_latest(self.db_path, document["id"])

        with self.assertRaises(AppError) as denied_schema:
            create_schema(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.users["editor"],
                name="editor_schema",
                version="1.0.0",
                schema_json={"type": "object"},
            )
        self.assertEqual(denied_schema.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_admin_can_create_schema_and_members_can_read_schema(self) -> None:
        schema = create_schema(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.users["admin"],
            name="admin_schema",
            version="1.0.0",
            schema_json={"type": "object"},
        )

        self.assertEqual(schema["created_by"], self.users["admin"])
        self.assertEqual(get_schema(self.db_path, schema["id"], actor_id=self.users["viewer"])["id"], schema["id"])
        self.assertEqual(
            list_project_schemas(self.db_path, self.project_id, actor_id=self.users["reviewer"])["schemas"][0]["id"],
            schema["id"],
        )


if __name__ == "__main__":
    unittest.main()
