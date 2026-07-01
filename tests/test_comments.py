from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.comment_service import (
    add_comment,
    create_comment_thread,
    list_comment_threads,
    reopen_comment_thread,
    resolve_comment_thread,
)
from app.database import connect, init_db, utc_now
from app.document_service import create_document, delete_document, get_history, patch_document
from app.errors import AppError, ErrorCode
from app.main import create_app


class CommentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.workspace_id = "workspace_comments"
        self.project_id = "project_comments"
        self.users = {
            "owner": "user_owner",
            "reviewer": "user_reviewer",
            "viewer": "user_viewer",
            "nonmember": "user_nonmember",
        }
        now = utc_now()
        with connect(self.db_path) as conn:
            for label, user_id in self.users.items():
                conn.execute(
                    "INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, f"comments-{label}@example.com", label.title(), now, now),
                )
            conn.execute(
                "INSERT INTO workspaces (id, name, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (self.workspace_id, "Comments Workspace", self.users["owner"], now, now),
            )
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (self.project_id, self.workspace_id, "Comments Project", None, now, now),
            )
            for role in ("owner", "reviewer", "viewer"):
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
            full_path="config/comments.json",
            content={"model": {"name": "baseline"}, "learning_rate": 0.1},
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

    def _thread_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM comment_threads WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def test_create_document_path_and_event_comment_threads(self) -> None:
        document = self._create_document()
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["owner"],
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.2}],
        )
        event_id = get_history(self.db_path, document["id"], actor_id=self.users["owner"])["events"][1]["id"]

        document_thread = create_comment_thread(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["reviewer"],
            anchor_type="document",
            body="Document-level memo",
        )
        path_thread = create_comment_thread(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["reviewer"],
            anchor_type="path",
            path="/model/name",
            body="Path-level memo",
        )
        event_thread = create_comment_thread(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["reviewer"],
            anchor_type="event",
            event_id=event_id,
            body="Event-level memo",
        )

        self.assertEqual(document_thread["anchor_type"], "document")
        self.assertEqual(path_thread["path"], "/model/name")
        self.assertEqual(event_thread["event_id"], event_id)
        listed = list_comment_threads(self.db_path, document_id=document["id"], actor_id=self.users["viewer"])
        self.assertEqual(len(listed["threads"]), 3)
        self.assertEqual(listed["threads"][0]["created_by_display_name"], "Reviewer")
        self.assertEqual(listed["threads"][0]["comments"][0]["author_display_name"], "Reviewer")
        self.assertEqual(self._event_count(document["id"]), 2)
        self.assertEqual(self._snapshot(document["id"])["learning_rate"], 0.2)

    def test_invalid_comment_anchor_rejected_without_thread(self) -> None:
        document = self._create_document()

        with self.assertRaises(AppError) as bad_path:
            create_comment_thread(
                self.db_path,
                document_id=document["id"],
                actor_id=self.users["reviewer"],
                anchor_type="path",
                path="model/name",
                body="Invalid path",
            )
        self.assertEqual(bad_path.exception.code, ErrorCode.INVALID_COMMENT_ANCHOR)

        with self.assertRaises(AppError) as bad_event:
            create_comment_thread(
                self.db_path,
                document_id=document["id"],
                actor_id=self.users["reviewer"],
                anchor_type="event",
                event_id="missing_event",
                body="Invalid event",
            )
        self.assertEqual(bad_event.exception.code, ErrorCode.INVALID_COMMENT_ANCHOR)
        self.assertEqual(self._thread_count(document["id"]), 0)

    def test_add_resolve_and_reopen_thread_without_document_mutation(self) -> None:
        document = self._create_document()
        before_snapshot = self._snapshot(document["id"])
        before_event_count = self._event_count(document["id"])
        thread = create_comment_thread(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["reviewer"],
            anchor_type="path",
            path="/learning_rate",
            body="Please verify this value.",
        )

        reply = add_comment(
            self.db_path,
            thread_id=thread["id"],
            actor_id=self.users["owner"],
            body="Verified.",
        )
        resolved = resolve_comment_thread(self.db_path, thread_id=thread["id"], actor_id=self.users["reviewer"])
        reopened = reopen_comment_thread(self.db_path, thread_id=thread["id"], actor_id=self.users["reviewer"])

        self.assertEqual(reply["body"], "Verified.")
        self.assertEqual(reply["author_display_name"], "Owner")
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["resolved_by_display_name"], "Reviewer")
        self.assertEqual(reopened["status"], "open")
        self.assertEqual(len(reopened["comments"]), 2)
        self.assertEqual(self._event_count(document["id"]), before_event_count)
        self.assertEqual(self._snapshot(document["id"]), before_snapshot)

    def test_viewer_can_list_but_cannot_write_comments_and_nonmember_denied(self) -> None:
        document = self._create_document()
        create_comment_thread(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["reviewer"],
            body="Existing comment",
        )

        self.assertEqual(
            len(list_comment_threads(self.db_path, document_id=document["id"], actor_id=self.users["viewer"])["threads"]),
            1,
        )
        with self.assertRaises(AppError) as viewer_denied:
            create_comment_thread(
                self.db_path,
                document_id=document["id"],
                actor_id=self.users["viewer"],
                body="Viewer write",
            )
        self.assertEqual(viewer_denied.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as nonmember_denied:
            list_comment_threads(self.db_path, document_id=document["id"], actor_id=self.users["nonmember"])
        self.assertEqual(nonmember_denied.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_soft_deleted_document_comments_are_listable_but_new_threads_are_rejected(self) -> None:
        document = self._create_document()
        create_comment_thread(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["reviewer"],
            body="Keep this audit note.",
        )
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["owner"],
            base_version=1,
        )

        listed = list_comment_threads(self.db_path, document_id=document["id"], actor_id=self.users["reviewer"])
        self.assertEqual(len(listed["threads"]), 1)
        self.assertEqual(listed["threads"][0]["created_by_display_name"], "Reviewer")
        with self.assertRaises(AppError) as rejected:
            create_comment_thread(
                self.db_path,
                document_id=document["id"],
                actor_id=self.users["reviewer"],
                body="New comment after delete",
            )
        self.assertEqual(rejected.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)

    def test_comments_table_is_append_only_at_db_level(self) -> None:
        document = self._create_document()
        thread = create_comment_thread(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["reviewer"],
            body="Immutable comment",
        )
        comment_id = thread["comments"][0]["id"]

        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE comments SET body = ? WHERE id = ?", ("changed", comment_id))
        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))

    def test_comment_routes_are_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/documents/{document_id}/comment-threads", "POST"), routes)
        self.assertIn(("/documents/{document_id}/comment-threads", "GET"), routes)
        self.assertIn(("/comment-threads/{thread_id}/comments", "POST"), routes)
        self.assertIn(("/comment-threads/{thread_id}/resolve", "POST"), routes)
        self.assertIn(("/comment-threads/{thread_id}/reopen", "POST"), routes)


if __name__ == "__main__":
    unittest.main()
