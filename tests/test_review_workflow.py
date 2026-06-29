from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.database import connect, init_db, utc_now
from app.document_service import assert_replay_matches_latest, create_document, get_document, get_history, patch_document
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.review_service import (
    apply_review_request,
    approve_review_request,
    comment_on_review_request,
    create_review_request,
    get_review_request,
    list_project_review_requests,
    request_review_changes,
)
from app.schema_service import create_schema


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.workspace_id = "workspace_review"
        self.project_id = "project_review"
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
                    (user_id, f"review-{label}@example.com", label.title(), now, now),
                )
            conn.execute(
                "INSERT INTO workspaces (id, name, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (self.workspace_id, "Review Workspace", self.users["owner"], now, now),
            )
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (self.project_id, self.workspace_id, "Review Project", None, now, now),
            )
            for role in ("owner", "admin", "editor", "reviewer", "viewer"):
                conn.execute(
                    "INSERT INTO project_members (id, project_id, user_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (f"member_{role}", self.project_id, self.users[role], role, now),
                )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_document(self, full_path: str = "config/review.json", value: int = 1) -> dict:
        return create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.users["owner"],
            full_path=full_path,
            content={"value": value},
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

    def _review_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM review_requests").fetchone()["count"]

    def _decision_count(self, review_request_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM review_decisions WHERE review_request_id = ?",
                (review_request_id,),
            ).fetchone()["count"]

    def _create_review(self, document_id: str, base_version: int = 1, value: int = 2) -> dict:
        return create_review_request(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.users["editor"],
            title="Update value",
            description="Proposed JSON change",
            changes=[
                {
                    "document_id": document_id,
                    "base_version": base_version,
                    "patch": [{"op": "replace", "path": "/value", "value": value}],
                    "reason": "Reviewed change",
                }
            ],
        )

    def test_create_review_request_records_proposal_without_document_mutation(self) -> None:
        document = self._create_document()
        review = self._create_review(document["id"])

        self.assertEqual(review["status"], "open")
        self.assertEqual(review["changes"][0]["changed_paths"], ["/value"])
        self.assertEqual(self._event_count(document["id"]), 1)
        self.assertEqual(self._snapshot(document["id"]), {"value": 1})
        listed = list_project_review_requests(self.db_path, project_id=self.project_id, actor_id=self.users["viewer"])
        self.assertEqual(listed["review_requests"][0]["id"], review["id"])

    def test_approve_and_apply_creates_document_event_and_marks_applied(self) -> None:
        document = self._create_document()
        review = self._create_review(document["id"])

        approved = approve_review_request(
            self.db_path,
            review_request_id=review["id"],
            actor_id=self.users["reviewer"],
            comment="Looks correct.",
        )
        applied = apply_review_request(
            self.db_path,
            review_request_id=review["id"],
            actor_id=self.users["editor"],
        )

        self.assertEqual(approved["status"], "approved")
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["applied_by"], self.users["editor"])
        self.assertEqual(applied["applied_documents"][0]["current_version"], 2)
        self.assertEqual(get_document(self.db_path, document["id"], actor_id=self.users["viewer"])["content"], {"value": 2})
        history = get_history(self.db_path, document["id"], actor_id=self.users["viewer"])
        self.assertEqual([event["event_type"] for event in history["events"]], ["create", "update"])
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_apply_requires_approval_and_reviewer_cannot_apply(self) -> None:
        document = self._create_document()
        review = self._create_review(document["id"])

        with self.assertRaises(AppError) as not_approved:
            apply_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["editor"])
        self.assertEqual(not_approved.exception.code, ErrorCode.INVALID_REVIEW_STATE)

        approve_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["reviewer"])
        with self.assertRaises(AppError) as reviewer_apply:
            apply_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["reviewer"])
        self.assertEqual(reviewer_apply.exception.code, ErrorCode.PERMISSION_DENIED)
        self.assertEqual(self._event_count(document["id"]), 1)

    def test_author_cannot_self_approve_and_failed_decision_writes_nothing(self) -> None:
        document = self._create_document()
        review = create_review_request(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.users["owner"],
            title="Owner-authored review",
            description=None,
            changes=[
                {
                    "document_id": document["id"],
                    "base_version": 1,
                    "patch": [{"op": "replace", "path": "/value", "value": 2}],
                }
            ],
        )

        with self.assertRaises(AppError) as self_approve:
            approve_review_request(
                self.db_path,
                review_request_id=review["id"],
                actor_id=self.users["owner"],
                comment="Approving my own change.",
            )
        self.assertEqual(self_approve.exception.code, ErrorCode.INVALID_REVIEW_STATE)
        loaded = get_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["viewer"])
        self.assertEqual(loaded["status"], "open")
        self.assertEqual(loaded["decisions"], [])
        self.assertEqual(self._event_count(document["id"]), 1)

        approved = approve_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["reviewer"])
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(self._decision_count(review["id"]), 1)

    def test_request_changes_blocks_apply_until_reapproved(self) -> None:
        document = self._create_document()
        review = self._create_review(document["id"])

        changed = request_review_changes(
            self.db_path,
            review_request_id=review["id"],
            actor_id=self.users["reviewer"],
            comment="Please justify this value.",
        )
        self.assertEqual(changed["status"], "changes_requested")

        with self.assertRaises(AppError) as blocked:
            apply_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["editor"])
        self.assertEqual(blocked.exception.code, ErrorCode.INVALID_REVIEW_STATE)

        approve_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["reviewer"])
        applied = apply_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["editor"])
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(self._snapshot(document["id"]), {"value": 2})

    def test_comment_only_decision_does_not_change_status_or_document(self) -> None:
        document = self._create_document()
        review = self._create_review(document["id"])

        commented = comment_on_review_request(
            self.db_path,
            review_request_id=review["id"],
            actor_id=self.users["reviewer"],
            comment="Leaving a note only.",
        )

        self.assertEqual(commented["status"], "open")
        self.assertEqual(commented["decisions"][0]["decision_type"], "comment")
        self.assertEqual(self._event_count(document["id"]), 1)
        self.assertEqual(self._snapshot(document["id"]), {"value": 1})

    def test_applied_review_is_terminal_for_later_decisions(self) -> None:
        document = self._create_document()
        review = self._create_review(document["id"])
        approve_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["reviewer"])
        apply_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["editor"])

        for action in (
            lambda: approve_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["reviewer"]),
            lambda: request_review_changes(self.db_path, review_request_id=review["id"], actor_id=self.users["reviewer"]),
            lambda: comment_on_review_request(
                self.db_path,
                review_request_id=review["id"],
                actor_id=self.users["reviewer"],
                comment="Late comment",
            ),
        ):
            with self.assertRaises(AppError) as terminal:
                action()
            self.assertEqual(terminal.exception.code, ErrorCode.INVALID_REVIEW_STATE)

        loaded = get_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["viewer"])
        self.assertEqual(loaded["status"], "applied")
        self.assertEqual(self._decision_count(review["id"]), 1)
        self.assertEqual(self._event_count(document["id"]), 2)
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_permission_boundaries_for_create_approve_and_read(self) -> None:
        document = self._create_document()

        with self.assertRaises(AppError) as viewer_create:
            create_review_request(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.users["viewer"],
                title="Viewer proposal",
                description=None,
                changes=[
                    {
                        "document_id": document["id"],
                        "base_version": 1,
                        "patch": [{"op": "replace", "path": "/value", "value": 2}],
                    }
                ],
            )
        self.assertEqual(viewer_create.exception.code, ErrorCode.PERMISSION_DENIED)

        review = self._create_review(document["id"])
        with self.assertRaises(AppError) as editor_approve:
            approve_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["editor"])
        self.assertEqual(editor_approve.exception.code, ErrorCode.PERMISSION_DENIED)

        loaded = get_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["viewer"])
        self.assertEqual(loaded["id"], review["id"])

        with self.assertRaises(AppError) as nonmember_read:
            get_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["nonmember"])
        self.assertEqual(nonmember_read.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_schema_invalid_proposed_change_rejected_without_review_or_event(self) -> None:
        schema = create_schema(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.users["admin"],
            name="bounded",
            version="1.0.0",
            schema_json={
                "type": "object",
                "properties": {"value": {"type": "number", "minimum": 0, "maximum": 10}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.users["owner"],
            full_path="config/schema-review.json",
            schema_id=schema["id"],
            content={"value": 1},
        )

        with self.assertRaises(AppError) as rejected:
            self._create_review(document["id"], value=99)
        self.assertEqual(rejected.exception.code, ErrorCode.SCHEMA_VALIDATION_FAILED)
        self.assertEqual(self._review_count(), 0)
        self.assertEqual(self._event_count(document["id"]), 1)
        self.assertEqual(self._snapshot(document["id"]), {"value": 1})

    def test_wrong_base_version_rejected_without_review_or_extra_event(self) -> None:
        document = self._create_document()
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.users["owner"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 3}],
        )

        with self.assertRaises(AppError) as stale:
            self._create_review(document["id"], base_version=1, value=4)
        self.assertEqual(stale.exception.code, ErrorCode.VERSION_CONFLICT)
        self.assertEqual(self._review_count(), 0)
        self.assertEqual(self._event_count(document["id"]), 2)
        self.assertEqual(self._snapshot(document["id"]), {"value": 3})

    def test_version_conflict_on_apply_rolls_back_all_review_apply_writes(self) -> None:
        first = self._create_document(full_path="config/first.json", value=1)
        second = self._create_document(full_path="config/second.json", value=10)
        review = create_review_request(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.users["editor"],
            title="Two document update",
            description=None,
            changes=[
                {
                    "document_id": first["id"],
                    "base_version": 1,
                    "patch": [{"op": "replace", "path": "/value", "value": 2}],
                },
                {
                    "document_id": second["id"],
                    "base_version": 1,
                    "patch": [{"op": "replace", "path": "/value", "value": 20}],
                },
            ],
        )
        patch_document(
            self.db_path,
            document_id=second["id"],
            actor_id=self.users["owner"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 11}],
        )
        approve_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["reviewer"])

        with self.assertRaises(AppError) as conflict:
            apply_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["editor"])
        self.assertEqual(conflict.exception.code, ErrorCode.VERSION_CONFLICT)

        self.assertEqual(self._snapshot(first["id"]), {"value": 1})
        self.assertEqual(self._event_count(first["id"]), 1)
        self.assertEqual(self._snapshot(second["id"]), {"value": 11})
        self.assertEqual(self._event_count(second["id"]), 2)
        self.assertEqual(
            get_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["viewer"])["status"],
            "approved",
        )

    def test_review_decisions_are_append_only_at_db_level(self) -> None:
        document = self._create_document()
        review = self._create_review(document["id"])
        approve_review_request(self.db_path, review_request_id=review["id"], actor_id=self.users["reviewer"])
        decision_id = get_review_request(
            self.db_path,
            review_request_id=review["id"],
            actor_id=self.users["viewer"],
        )["decisions"][0]["id"]

        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE review_decisions SET body = ? WHERE id = ?", ("changed", decision_id))
        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM review_decisions WHERE id = ?", (decision_id,))

    def test_review_request_changes_are_immutable_at_db_level(self) -> None:
        document = self._create_document()
        review = self._create_review(document["id"])
        change_id = review["changes"][0]["id"]

        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE review_request_changes SET reason = ? WHERE id = ?",
                    ("changed", change_id),
                )
        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM review_request_changes WHERE id = ?", (change_id,))

    def test_review_routes_are_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/review-requests", "POST"), routes)
        self.assertIn(("/projects/{project_id}/review-requests", "GET"), routes)
        self.assertIn(("/review-requests/{review_request_id}", "GET"), routes)
        self.assertIn(("/review-requests/{review_request_id}/approve", "POST"), routes)
        self.assertIn(("/review-requests/{review_request_id}/request-changes", "POST"), routes)
        self.assertIn(("/review-requests/{review_request_id}/comment", "POST"), routes)
        self.assertIn(("/review-requests/{review_request_id}/apply", "POST"), routes)


if __name__ == "__main__":
    unittest.main()
