from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db, utc_now
from app.document_service import create_document, get_document
from app.errors import AppError, ErrorCode
from app.export_service import export_project_archive
from app.main import create_app
from app.review_service import apply_review_request, get_review_request, list_project_review_requests
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class ReviewChangeJsonMalformedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.editor = create_user(self.db_path, email="editor@example.com", display_name="Editor")
        self.viewer = create_user(self.db_path, email="viewer@example.com", display_name="Viewer")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )
        for user, role in ((self.editor, "editor"), (self.viewer, "viewer")):
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=user["id"],
                role=role,
            )
        self.document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/review.json",
            content={"value": 1},
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (self.document["id"],),
            ).fetchone()["count"]

    def _review_row(self, review_request_id: str) -> dict:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM review_requests WHERE id = ?", (review_request_id,)).fetchone()
            return dict(row)

    def _insert_approved_review_change(
        self,
        *,
        review_request_id: str = "review_malformed",
        change_id: str = "review_change_malformed",
        patch_json: str | None = None,
        changed_paths_json: str | None = None,
    ) -> tuple[str, str]:
        now = utc_now()
        patch_json = patch_json if patch_json is not None else json.dumps(
            [{"op": "replace", "path": "/value", "value": 2}],
            separators=(",", ":"),
        )
        changed_paths_json = changed_paths_json if changed_paths_json is not None else json.dumps(
            ["/value"],
            separators=(",", ":"),
        )
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_requests (
                    id,
                    project_id,
                    author_id,
                    status,
                    title,
                    description,
                    created_at,
                    updated_at,
                    applied_by,
                    applied_at
                )
                VALUES (?, ?, ?, 'approved', ?, NULL, ?, ?, NULL, NULL)
                """,
                (
                    review_request_id,
                    self.project["id"],
                    self.editor["id"],
                    "Malformed proposal",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO review_request_changes (
                    id,
                    review_request_id,
                    document_id,
                    base_version,
                    patch,
                    changed_paths,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    change_id,
                    review_request_id,
                    self.document["id"],
                    patch_json,
                    changed_paths_json,
                    "malformed persisted proposal",
                    now,
                ),
            )
        return review_request_id, change_id

    def test_review_get_list_and_http_read_report_malformed_patch_json(self) -> None:
        review_id, change_id = self._insert_approved_review_change(patch_json='{"op":')

        detail = get_review_request(self.db_path, review_request_id=review_id, actor_id=self.viewer["id"])
        change = detail["changes"][0]
        self.assertEqual(change["id"], change_id)
        self.assertIsNone(change["patch"])
        self.assertEqual(change["changed_paths"], ["/value"])
        self.assertEqual(change["json_errors"][0]["field"], "patch")
        self.assertIn("message", change["json_errors"][0])

        listed = list_project_review_requests(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.viewer["id"],
        )
        listed_change = listed["review_requests"][0]["changes"][0]
        self.assertIsNone(listed_change["patch"])
        self.assertEqual(listed_change["json_errors"][0]["field"], "patch")

        client = TestClient(create_app(self.db_path))
        response = client.get(
            f"/review-requests/{review_id}",
            headers={"X-Actor-Id": self.viewer["id"]},
        )
        self.assertEqual(response.status_code, 200)
        payload_change = response.json()["changes"][0]
        self.assertIsNone(payload_change["patch"])
        self.assertEqual(payload_change["json_errors"][0]["field"], "patch")

    def test_review_read_and_export_report_malformed_changed_paths_json(self) -> None:
        review_id, _ = self._insert_approved_review_change(
            review_request_id="review_bad_changed_paths",
            change_id="review_change_bad_changed_paths",
            changed_paths_json='["/value"',
        )

        detail = get_review_request(self.db_path, review_request_id=review_id, actor_id=self.viewer["id"])
        change = detail["changes"][0]
        self.assertEqual(change["patch"], [{"op": "replace", "path": "/value", "value": 2}])
        self.assertIsNone(change["changed_paths"])
        self.assertEqual(change["json_errors"][0]["field"], "changed_paths")

        archive = export_project_archive(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            include_reviews=True,
        )
        exported_change = archive["reviews"][0]["changes"][0]
        self.assertIsNone(exported_change["changed_paths"])
        self.assertEqual(exported_change["json_errors"][0]["field"], "changed_paths")

    def test_review_apply_rejects_malformed_patch_without_partial_mutation(self) -> None:
        review_id, change_id = self._insert_approved_review_change(patch_json='{"op":')
        before_review = self._review_row(review_id)

        with self.assertRaises(AppError) as rejected:
            apply_review_request(self.db_path, review_request_id=review_id, actor_id=self.editor["id"])

        self.assertEqual(rejected.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(rejected.exception.details["diagnostic_code"], "REVIEW_CHANGE_JSON_DECODE_FAILED")
        self.assertEqual(rejected.exception.details["review_request_id"], review_id)
        self.assertEqual(rejected.exception.details["review_change_id"], change_id)
        self.assertEqual(rejected.exception.details["document_id"], self.document["id"])
        self.assertEqual(rejected.exception.details["field"], "patch")

        after_review = self._review_row(review_id)
        self.assertEqual(after_review["status"], before_review["status"])
        self.assertIsNone(after_review["applied_by"])
        self.assertIsNone(after_review["applied_at"])
        self.assertEqual(self._event_count(), 1)
        self.assertEqual(
            get_document(self.db_path, self.document["id"], actor_id=self.viewer["id"])["content"],
            {"value": 1},
        )

        client = TestClient(create_app(self.db_path))
        response = client.post(
            f"/review-requests/{review_id}/apply",
            headers={"X-Actor-Id": self.editor["id"]},
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.INTERNAL_ERROR)
        self.assertEqual(
            response.json()["error"]["details"]["diagnostic_code"],
            "REVIEW_CHANGE_JSON_DECODE_FAILED",
        )
        self.assertEqual(self._event_count(), 1)


if __name__ == "__main__":
    unittest.main()
