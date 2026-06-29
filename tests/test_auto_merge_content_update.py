from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.database import connect, init_db, utc_now
from app.document_service import assert_replay_matches_latest, create_document, get_document, get_history, update_document_content
from app.errors import AppError, ErrorCode


class AutoMergeContentUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner_id = "user_owner"
        self.editor_id = "user_editor"
        self.workspace_id = "workspace_001"
        self.project_id = "project_001"
        now = utc_now()
        with connect(self.db_path) as conn:
            for user_id, email, name in (
                (self.owner_id, "owner@example.com", "Owner"),
                (self.editor_id, "editor@example.com", "Editor"),
            ):
                conn.execute(
                    "INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, email, name, now, now),
                )
            conn.execute(
                "INSERT INTO workspaces (id, name, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (self.workspace_id, "Workspace", self.owner_id, now, now),
            )
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (self.project_id, self.workspace_id, "Project", None, now, now),
            )
            for member_id, user_id, role in (
                ("member_owner", self.owner_id, "owner"),
                ("member_editor", self.editor_id, "editor"),
            ):
                conn.execute(
                    "INSERT INTO project_members (id, project_id, user_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (member_id, self.project_id, user_id, role, now),
                )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def test_stale_content_update_auto_merges_non_overlapping_object_paths(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.owner_id,
            full_path="config/merge.json",
            content={"a": 1, "b": 1},
        )
        update_document_content(
            self.db_path,
            document_id=document["id"],
            actor_id=self.editor_id,
            base_version=1,
            content={"a": 1, "b": 2},
        )

        merged = update_document_content(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner_id,
            base_version=1,
            content={"a": 2, "b": 1},
            merge_strategy="auto",
            reason="safe auto merge",
        )

        self.assertTrue(merged["auto_merged"])
        self.assertEqual(merged["previous_version"], 2)
        self.assertEqual(merged["current_version"], 3)
        self.assertEqual(get_document(self.db_path, document["id"], actor_id=self.owner_id)["content"], {"a": 2, "b": 2})
        events = get_history(self.db_path, document["id"], actor_id=self.owner_id)["events"]
        self.assertEqual([(event["base_version"], event["result_version"]) for event in events], [(0, 1), (1, 2), (2, 3)])
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_stale_content_update_auto_merge_rejects_overlapping_path_without_event(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.owner_id,
            full_path="config/conflict.json",
            content={"a": 1, "b": 1},
        )
        update_document_content(
            self.db_path,
            document_id=document["id"],
            actor_id=self.editor_id,
            base_version=1,
            content={"a": 3, "b": 1},
        )
        before_events = self._event_count(document["id"])

        with self.assertRaises(AppError) as raised:
            update_document_content(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
                base_version=1,
                content={"a": 2, "b": 1},
                merge_strategy="auto",
            )

        self.assertEqual(raised.exception.code, ErrorCode.VERSION_CONFLICT)
        self.assertEqual(self._event_count(document["id"]), before_events)
        self.assertEqual(get_document(self.db_path, document["id"], actor_id=self.owner_id)["content"], {"a": 3, "b": 1})
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_stale_content_update_auto_merge_rejects_array_path_without_event(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.owner_id,
            full_path="config/array.json",
            content={"items": [{"value": 1}], "b": 1},
        )
        update_document_content(
            self.db_path,
            document_id=document["id"],
            actor_id=self.editor_id,
            base_version=1,
            content={"items": [{"value": 1}], "b": 2},
        )
        before_events = self._event_count(document["id"])

        with self.assertRaises(AppError) as raised:
            update_document_content(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner_id,
                base_version=1,
                content={"items": [{"value": 2}], "b": 1},
                merge_strategy="auto",
            )

        self.assertEqual(raised.exception.code, ErrorCode.VERSION_CONFLICT)
        self.assertEqual(raised.exception.details["auto_merge"]["reason"], "array_path_changed")
        self.assertEqual(self._event_count(document["id"]), before_events)
        self.assertEqual(
            get_document(self.db_path, document["id"], actor_id=self.owner_id)["content"],
            {"items": [{"value": 1}], "b": 2},
        )
        assert_replay_matches_latest(self.db_path, document["id"])


if __name__ == "__main__":
    unittest.main()
