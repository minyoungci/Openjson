from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from fastapi.exceptions import RequestValidationError

from app.database import connect, init_db, utc_now
from app.document_service import (
    assert_replay_matches_latest,
    create_document,
    delete_document,
    diff_document_versions,
    get_document,
    get_history,
    patch_document,
    preview_document_patch,
    reconstruct_document_at_version,
    rollback_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from scripts.seed_dev import seed as seed_dev


class DocumentFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.actor_id = "user_001"
        self.workspace_id = "workspace_001"
        self.project_id = "project_001"
        now = utc_now()
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (self.actor_id, "user@example.com", "Test User", now, now),
            )
            conn.execute(
                "INSERT INTO workspaces (id, name, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (self.workspace_id, "Workspace", self.actor_id, now, now),
            )
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (self.project_id, self.workspace_id, "Project", None, now, now),
            )
            conn.execute(
                "INSERT INTO project_members (id, project_id, user_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
                ("member_001", self.project_id, self.actor_id, "owner", now),
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_document(self) -> dict:
        return create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/model.json",
            content={"model": "baseline", "learning_rate": 0.001, "obsolete": True},
        )

    def _create_custom_document(self, content: object, full_path: str = "config/custom.json") -> dict:
        return create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path=full_path,
            content=content,
        )

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _total_event_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]

    def _document_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"]

    def _current_snapshot(self, document_id: str) -> object:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            return json.loads(row["current_snapshot_json"])

    def _document_version(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_version FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            return row["current_version"]

    def test_create_valid_json_document(self) -> None:
        document = self._create_document()

        self.assertEqual(document["project_id"], self.project_id)
        self.assertEqual(document["full_path"], "config/model.json")
        self.assertEqual(document["current_version"], 1)
        self.assertEqual(document["content"]["learning_rate"], 0.001)

        history = get_history(self.db_path, document["id"], actor_id=self.actor_id)
        self.assertEqual(len(history["events"]), 1)
        self.assertEqual(history["events"][0]["event_type"], "create")

    def test_reject_invalid_json_document(self) -> None:
        with self.assertRaises(AppError) as raised:
            create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                full_path="config/bad.json",
                content={"bad": math.nan},
            )

        self.assertEqual(raised.exception.code, ErrorCode.INVALID_JSON_SYNTAX)

    def test_invalid_full_path_policy_rejects_before_document_event_creation(self) -> None:
        invalid_paths = [
            "",
            "   ",
            " config/model.json",
            "config/model.json ",
            "config\\model.json",
            "/config/model.json",
            "config/model.json/",
            "config//model.json",
            "config/./model.json",
            "config/../model.json",
        ]

        for full_path in invalid_paths:
            with self.assertRaises(AppError) as raised:
                create_document(
                    self.db_path,
                    project_id=self.project_id,
                    actor_id=self.actor_id,
                    full_path=full_path,
                    content={"value": 1},
                )
            self.assertEqual(raised.exception.code, ErrorCode.PATCH_APPLY_FAILED)
            self.assertEqual(self._document_count(), 0)
            self.assertEqual(self._total_event_count(), 0)

    def test_http_invalid_full_path_returns_error_without_document_event_creation(self) -> None:
        client = TestClient(create_app(self.db_path))

        for full_path in ("/config/model.json", "config//model.json", "config/../model.json"):
            response = client.post(
                f"/projects/{self.project_id}/documents",
                headers={"X-Actor-Id": self.actor_id},
                json={"full_path": full_path, "content": {"value": 1}},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], ErrorCode.PATCH_APPLY_FAILED)
            self.assertEqual(self._document_count(), 0)
            self.assertEqual(self._total_event_count(), 0)

    def test_reject_scalar_document_content(self) -> None:
        with self.assertRaises(AppError) as raised:
            self._create_custom_document(1)

        self.assertEqual(raised.exception.code, ErrorCode.INVALID_JSON_SYNTAX)

    def test_get_document(self) -> None:
        created = self._create_document()

        loaded = get_document(self.db_path, created["id"], actor_id=self.actor_id)

        self.assertEqual(loaded["id"], created["id"])
        self.assertEqual(loaded["content"], created["content"])

    def test_patch_document_successfully(self) -> None:
        created = self._create_document()

        updated = patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
            reason="Update default learning rate",
        )

        self.assertEqual(updated["previous_version"], 1)
        self.assertEqual(updated["current_version"], 2)
        self.assertEqual(updated["content"]["learning_rate"], 0.0005)
        self.assertEqual(updated["changed_paths"], ["/learning_rate"])
        self.assertTrue(updated["validation"]["valid"])

    def test_patch_preview_returns_candidate_without_event_version_or_snapshot_change(self) -> None:
        created = self._create_document()

        preview = preview_document_patch(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )

        self.assertEqual(preview["document_id"], created["id"])
        self.assertEqual(preview["base_version"], 1)
        self.assertEqual(preview["current_version"], 1)
        self.assertFalse(preview["persisted"])
        self.assertEqual(preview["candidate_content"]["learning_rate"], 0.0005)
        self.assertEqual(preview["changed_paths"], ["/learning_rate"])
        self.assertEqual(preview["inverse_patch"], [{"op": "replace", "path": "/learning_rate", "value": 0.001}])
        self.assertEqual(preview["before_values"], [{"path": "/learning_rate", "exists": True, "value": 0.001}])
        self.assertEqual(preview["after_values"], [{"path": "/learning_rate", "exists": True, "value": 0.0005}])
        self.assertTrue(preview["validation"]["valid"])
        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._document_version(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"]), created["content"])
        assert_replay_matches_latest(self.db_path, created["id"])

    def test_http_patch_preview_returns_candidate_without_partial_mutation(self) -> None:
        created = self._create_document()
        client = TestClient(create_app(self.db_path))

        response = client.post(
            f"/documents/{created['id']}/patch-preview",
            headers={"X-Actor-Id": self.actor_id},
            json={"base_version": 1, "patch": [{"op": "replace", "path": "/learning_rate", "value": 0.0005}]},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["persisted"])
        self.assertEqual(body["candidate_content"]["learning_rate"], 0.0005)
        self.assertEqual(body["changed_paths"], ["/learning_rate"])
        self.assertEqual(body["inverse_patch"], [{"op": "replace", "path": "/learning_rate", "value": 0.001}])
        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._document_version(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"]), created["content"])

    def test_patch_preview_reuses_conflict_and_noop_policy_without_partial_mutation(self) -> None:
        created = self._create_custom_document({"value": 1})

        with self.assertRaises(AppError) as conflict:
            preview_document_patch(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=2,
                patch=[{"op": "replace", "path": "/value", "value": 2}],
            )
        with self.assertRaises(AppError) as noop:
            preview_document_patch(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[{"op": "replace", "path": "/value", "value": 1}],
            )

        self.assertEqual(conflict.exception.code, ErrorCode.VERSION_CONFLICT)
        self.assertEqual(conflict.exception.details["client_base_version"], 2)
        self.assertEqual(conflict.exception.details["server_current_version"], 1)
        self.assertEqual(conflict.exception.details["document_id"], created["id"])
        self.assertEqual(conflict.exception.details["project_id"], created["project_id"])
        self.assertEqual(conflict.exception.details["full_path"], created["full_path"])
        self.assertEqual(conflict.exception.details["conflict_policy"], "reject_stale_base_version")
        self.assertEqual(
            conflict.exception.details["reload"],
            {"method": "GET", "endpoint": f"/documents/{created['id']}/editor-state"},
        )
        self.assertEqual(conflict.exception.details["latest_event"]["id"], created["event_id"])
        self.assertEqual(conflict.exception.details["latest_event"]["event_type"], "create")
        self.assertEqual(conflict.exception.details["latest_event"]["result_version"], 1)
        self.assertEqual(noop.exception.code, ErrorCode.PATCH_APPLY_FAILED)
        self.assertEqual(noop.exception.details["message"], "Patch does not change document content.")
        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._document_version(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"]), {"value": 1})

    def test_patch_preview_rejects_soft_deleted_document_without_partial_mutation(self) -> None:
        created = self._create_custom_document({"value": 1})
        delete_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
        )
        before_event_count = self._event_count(created["id"])
        before_version = self._document_version(created["id"])
        before_snapshot = self._current_snapshot(created["id"])

        with self.assertRaises(AppError) as raised:
            preview_document_patch(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=before_version,
                patch=[{"op": "replace", "path": "/value", "value": 2}],
            )

        self.assertEqual(raised.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)
        self.assertEqual(self._event_count(created["id"]), before_event_count)
        self.assertEqual(self._document_version(created["id"]), before_version)
        self.assertEqual(self._current_snapshot(created["id"]), before_snapshot)
        history = get_history(self.db_path, created["id"], actor_id=self.actor_id)
        self.assertEqual([event["event_type"] for event in history["events"]], ["create", "delete"])
        assert_replay_matches_latest(self.db_path, created["id"])

    def test_reject_patch_with_wrong_base_version(self) -> None:
        created = self._create_document()

        with self.assertRaises(AppError) as raised:
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=0,
                patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
            )

        self.assertEqual(raised.exception.code, ErrorCode.VERSION_CONFLICT)
        self.assertEqual(raised.exception.details["client_base_version"], 0)
        self.assertEqual(raised.exception.details["server_current_version"], 1)
        self.assertEqual(raised.exception.details["document_id"], created["id"])
        self.assertEqual(raised.exception.details["project_id"], created["project_id"])
        self.assertEqual(raised.exception.details["full_path"], created["full_path"])
        self.assertEqual(raised.exception.details["conflict_policy"], "reject_stale_base_version")
        self.assertEqual(
            raised.exception.details["reload"],
            {"method": "GET", "endpoint": f"/documents/{created['id']}/editor-state"},
        )
        self.assertEqual(raised.exception.details["latest_event"]["id"], created["event_id"])
        self.assertEqual(raised.exception.details["latest_event"]["event_type"], "create")
        self.assertEqual(raised.exception.details["latest_event"]["result_version"], 1)
        self.assertEqual(self._event_count(created["id"]), 1)

    def test_store_document_event_after_patch_with_inverse_and_values(self) -> None:
        created = self._create_document()
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )

        history = get_history(self.db_path, created["id"], actor_id=self.actor_id)
        event = history["events"][1]

        self.assertEqual(event["event_type"], "update")
        self.assertEqual(event["base_version"], 1)
        self.assertEqual(event["result_version"], 2)
        self.assertEqual(event["inverse_patch"], [{"op": "replace", "path": "/learning_rate", "value": 0.001}])
        self.assertEqual(event["before_values"], [{"path": "/learning_rate", "exists": True, "value": 0.001}])
        self.assertEqual(event["after_values"], [{"path": "/learning_rate", "exists": True, "value": 0.0005}])

    def test_root_path_add_replace_and_remove_policy(self) -> None:
        created = self._create_custom_document({"root": "initial"})

        replaced = patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "", "value": {"root": "replaced"}}],
        )
        self.assertEqual(replaced["content"], {"root": "replaced"})

        added_root = patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=2,
            patch=[{"op": "add", "path": "", "value": [{"root": "array"}]}],
        )
        self.assertEqual(added_root["content"], [{"root": "array"}])

        with self.assertRaises(AppError) as raised:
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=3,
                patch=[{"op": "remove", "path": ""}],
            )
        self.assertEqual(raised.exception.code, ErrorCode.PATCH_APPLY_FAILED)
        self.assertEqual(self._event_count(created["id"]), 3)

    def test_nested_object_path_patch(self) -> None:
        created = self._create_custom_document({"nested": {"value": 1}})

        updated = patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/nested/value", "value": 2}],
        )

        self.assertEqual(updated["content"], {"nested": {"value": 2}})
        assert_replay_matches_latest(self.db_path, created["id"])

    def test_array_index_patch_and_inverse_append_path(self) -> None:
        created = self._create_custom_document({"items": [{"id": "a"}, {"id": "b"}]})

        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/items/1/id", "value": "b2"}],
        )
        updated = patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=2,
            patch=[{"op": "add", "path": "/items/-", "value": {"id": "c"}}],
        )

        self.assertEqual(updated["content"]["items"], [{"id": "a"}, {"id": "b2"}, {"id": "c"}])
        append_event = get_history(self.db_path, created["id"], actor_id=self.actor_id)["events"][2]
        self.assertEqual(updated["changed_paths"], ["/items/2"])
        self.assertEqual(append_event["changed_paths"], ["/items/2"])
        self.assertEqual(append_event["inverse_patch"], [{"op": "remove", "path": "/items/2"}])
        self.assertEqual(append_event["before_values"], [{"path": "/items/2", "exists": False, "value": None}])
        self.assertEqual(append_event["after_values"], [{"path": "/items/2", "exists": True, "value": {"id": "c"}}])

    def test_json_pointer_escaping(self) -> None:
        created = self._create_custom_document({"a/b": 1, "c~d": 2})

        updated = patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[
                {"op": "replace", "path": "/a~1b", "value": 10},
                {"op": "replace", "path": "/c~0d", "value": 20},
            ],
        )

        self.assertEqual(updated["content"], {"a/b": 10, "c~d": 20})

    def test_invalid_json_pointer_escape_rejected_without_event_version_or_snapshot_change(self) -> None:
        created = self._create_custom_document({"a~2b": 1, "value": 1})

        for bad_path in ("/a~2b", "/value~"):
            with self.assertRaises(AppError) as raised:
                patch_document(
                    self.db_path,
                    document_id=created["id"],
                    actor_id=self.actor_id,
                    base_version=1,
                    patch=[{"op": "replace", "path": bad_path, "value": 2}],
                )

            self.assertEqual(raised.exception.code, ErrorCode.PATCH_APPLY_FAILED)
            self.assertIn("JSON Pointer", raised.exception.details["message"])
            self.assertEqual(self._event_count(created["id"]), 1)
            self.assertEqual(self._document_version(created["id"]), 1)
            self.assertEqual(self._current_snapshot(created["id"]), {"a~2b": 1, "value": 1})

    def test_unsupported_patch_operations_are_rejected(self) -> None:
        for operation in ("move", "copy", "test"):
            created = self._create_custom_document({"value": 1}, full_path=f"config/{operation}.json")
            with self.assertRaises(AppError) as raised:
                patch_document(
                    self.db_path,
                    document_id=created["id"],
                    actor_id=self.actor_id,
                    base_version=1,
                    patch=[{"op": operation, "path": "/value", "value": 1}],
                )
            self.assertEqual(raised.exception.code, ErrorCode.UNSUPPORTED_PATCH_OPERATION)
            self.assertEqual(self._event_count(created["id"]), 1)

    def test_invalid_path_and_nonexistent_paths_are_rejected_without_event(self) -> None:
        created = self._create_custom_document({"value": 1})

        invalid_patches = [
            [{"op": "replace", "path": "value", "value": 2}],
            [{"op": "remove", "path": "/missing"}],
            [{"op": "replace", "path": "/missing", "value": 2}],
        ]
        for candidate_patch in invalid_patches:
            with self.assertRaises(AppError) as raised:
                patch_document(
                    self.db_path,
                    document_id=created["id"],
                    actor_id=self.actor_id,
                    base_version=1,
                    patch=candidate_patch,
                )
            self.assertEqual(raised.exception.code, ErrorCode.PATCH_APPLY_FAILED)
            self.assertEqual(self._event_count(created["id"]), 1)
            self.assertEqual(self._current_snapshot(created["id"]), {"value": 1})

    def test_malformed_patch_payload_rejected_without_event(self) -> None:
        created = self._create_custom_document({"value": 1})

        with self.assertRaises(AppError) as raised:
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch={"op": "replace", "path": "/value", "value": 2},
            )

        self.assertEqual(raised.exception.code, ErrorCode.PATCH_APPLY_FAILED)
        self.assertEqual(self._event_count(created["id"]), 1)

    def test_empty_update_patch_rejected_without_event_version_or_snapshot_change(self) -> None:
        created = self._create_custom_document({"value": 1})

        with self.assertRaises(AppError) as raised:
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[],
            )

        self.assertEqual(raised.exception.code, ErrorCode.PATCH_APPLY_FAILED)
        self.assertEqual(raised.exception.details["message"], "Patch must contain at least one operation.")
        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._document_version(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"]), {"value": 1})

    def test_http_empty_update_patch_returns_error_without_partial_mutation(self) -> None:
        created = self._create_custom_document({"value": 1})
        client = TestClient(create_app(self.db_path))

        response = client.patch(
            f"/documents/{created['id']}",
            headers={"X-Actor-Id": self.actor_id},
            json={"base_version": 1, "patch": []},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.PATCH_APPLY_FAILED)
        self.assertEqual(
            response.json()["error"]["details"]["message"],
            "Patch must contain at least one operation.",
        )
        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._document_version(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"]), {"value": 1})

    def test_semantic_noop_update_patch_rejected_without_event_version_or_snapshot_change(self) -> None:
        cases = [
            ("replace same scalar", [{"op": "replace", "path": "/value", "value": 1}]),
            ("add existing same scalar", [{"op": "add", "path": "/value", "value": 1}]),
            ("replace same root", [{"op": "replace", "path": "", "value": {"value": 1}}]),
            (
                "canceling multi-operation patch",
                [
                    {"op": "replace", "path": "/value", "value": 2},
                    {"op": "replace", "path": "/value", "value": 1},
                ],
            ),
        ]

        for index, (label, patch) in enumerate(cases, start=1):
            with self.subTest(label=label):
                created = self._create_custom_document({"value": 1}, full_path=f"config/noop-{index}.json")

                with self.assertRaises(AppError) as raised:
                    patch_document(
                        self.db_path,
                        document_id=created["id"],
                        actor_id=self.actor_id,
                        base_version=1,
                        patch=patch,
                    )

                self.assertEqual(raised.exception.code, ErrorCode.PATCH_APPLY_FAILED)
                self.assertEqual(raised.exception.details["message"], "Patch does not change document content.")
                self.assertEqual(self._event_count(created["id"]), 1)
                self.assertEqual(self._document_version(created["id"]), 1)
                self.assertEqual(self._current_snapshot(created["id"]), {"value": 1})
                assert_replay_matches_latest(self.db_path, created["id"])

    def test_http_semantic_noop_update_patch_returns_error_without_partial_mutation(self) -> None:
        created = self._create_custom_document({"value": 1})
        client = TestClient(create_app(self.db_path))

        response = client.patch(
            f"/documents/{created['id']}",
            headers={"X-Actor-Id": self.actor_id},
            json={"base_version": 1, "patch": [{"op": "replace", "path": "/value", "value": 1}]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.PATCH_APPLY_FAILED)
        self.assertEqual(
            response.json()["error"]["details"]["message"],
            "Patch does not change document content.",
        )
        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._document_version(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"]), {"value": 1})
        assert_replay_matches_latest(self.db_path, created["id"])

    def test_multi_operation_patch_failure_is_atomic_without_partial_mutation(self) -> None:
        created = self._create_custom_document({"value": 1, "stable": True})

        with self.assertRaises(AppError) as raised:
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[
                    {"op": "replace", "path": "/value", "value": 2},
                    {"op": "replace", "path": "/missing", "value": "should fail"},
                ],
            )

        self.assertEqual(raised.exception.code, ErrorCode.PATCH_APPLY_FAILED)
        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._document_version(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"]), {"value": 1, "stable": True})
        assert_replay_matches_latest(self.db_path, created["id"])

    def test_http_multi_operation_patch_failure_is_atomic_without_partial_mutation(self) -> None:
        created = self._create_custom_document({"value": 1, "stable": True})
        client = TestClient(create_app(self.db_path))

        response = client.patch(
            f"/documents/{created['id']}",
            headers={"X-Actor-Id": self.actor_id},
            json={
                "base_version": 1,
                "patch": [
                    {"op": "replace", "path": "/value", "value": 2},
                    {"op": "replace", "path": "/missing", "value": "should fail"},
                ],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.PATCH_APPLY_FAILED)
        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._document_version(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"]), {"value": 1, "stable": True})
        assert_replay_matches_latest(self.db_path, created["id"])

    def test_root_patch_to_scalar_rejected_without_snapshot_change(self) -> None:
        created = self._create_custom_document({"value": 1})

        with self.assertRaises(AppError) as raised:
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[{"op": "replace", "path": "", "value": 1}],
            )

        self.assertEqual(raised.exception.code, ErrorCode.INVALID_JSON_SYNTAX)
        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"]), {"value": 1})

    def test_duplicate_full_path_active_document_rejected_but_allowed_after_soft_delete(self) -> None:
        first = self._create_custom_document({"value": 1}, full_path="config/duplicate.json")

        with self.assertRaises(AppError) as raised:
            self._create_custom_document({"value": 2}, full_path="config/duplicate.json")
        self.assertEqual(raised.exception.code, ErrorCode.PATCH_APPLY_FAILED)

        delete_document(
            self.db_path,
            document_id=first["id"],
            actor_id=self.actor_id,
            base_version=1,
        )
        second = self._create_custom_document({"value": 2}, full_path="config/duplicate.json")
        self.assertNotEqual(first["id"], second["id"])

    def test_unknown_actor_is_permission_denied(self) -> None:
        with self.assertRaises(AppError) as raised:
            create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id="missing_user",
                full_path="config/permission.json",
                content={"value": 1},
            )

        self.assertEqual(raised.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_rollback_creates_new_event_and_preserves_history(self) -> None:
        created = self._create_document()
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )

        rolled_back = rollback_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=2,
            target_version=1,
            reason="Rollback to stable config",
        )

        self.assertEqual(rolled_back["current_version"], 3)
        self.assertEqual(rolled_back["content"]["learning_rate"], 0.001)

        history = get_history(self.db_path, created["id"], actor_id=self.actor_id)
        self.assertEqual(len(history["events"]), 3)
        self.assertEqual(history["events"][2]["event_type"], "rollback")
        self.assertEqual(history["events"][2]["base_version"], 2)
        self.assertEqual(history["events"][2]["result_version"], 3)

    def test_rollback_rejects_current_or_future_target_without_partial_mutation(self) -> None:
        created = self._create_document()
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )
        before_snapshot = self._current_snapshot(created["id"])
        before_event_count = self._event_count(created["id"])
        before_version = self._document_version(created["id"])

        for target_version in (2, 3):
            with self.assertRaises(AppError) as raised:
                rollback_document(
                    self.db_path,
                    document_id=created["id"],
                    actor_id=self.actor_id,
                    base_version=2,
                    target_version=target_version,
                )

            self.assertEqual(raised.exception.code, ErrorCode.INVALID_VERSION_RANGE)
            self.assertEqual(raised.exception.details["base_version"], 2)
            self.assertEqual(raised.exception.details["target_version"], target_version)
            self.assertEqual(self._event_count(created["id"]), before_event_count)
            self.assertEqual(self._document_version(created["id"]), before_version)
            self.assertEqual(self._current_snapshot(created["id"]), before_snapshot)

        assert_replay_matches_latest(self.db_path, created["id"])

    def test_http_rollback_rejects_current_target_without_partial_mutation(self) -> None:
        created = self._create_document()
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )
        client = TestClient(create_app(self.db_path))
        before_snapshot = self._current_snapshot(created["id"])

        response = client.post(
            f"/documents/{created['id']}/rollback",
            headers={"X-Actor-Id": self.actor_id},
            json={"base_version": 2, "target_version": 2},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.INVALID_VERSION_RANGE)
        self.assertEqual(response.json()["error"]["details"]["base_version"], 2)
        self.assertEqual(response.json()["error"]["details"]["target_version"], 2)
        self.assertEqual(self._event_count(created["id"]), 2)
        self.assertEqual(self._document_version(created["id"]), 2)
        self.assertEqual(self._current_snapshot(created["id"]), before_snapshot)
        assert_replay_matches_latest(self.db_path, created["id"])

    def test_replay_all_events_reconstructs_latest_snapshot(self) -> None:
        created = self._create_document()
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )
        rollback_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=2,
            target_version=1,
        )

        assert_replay_matches_latest(self.db_path, created["id"])
        latest = get_document(self.db_path, created["id"], actor_id=self.actor_id)
        replayed = reconstruct_document_at_version(self.db_path, created["id"], latest["current_version"])
        self.assertEqual(replayed, latest["content"])

    def test_soft_delete_records_event_without_deleting_history(self) -> None:
        created = self._create_document()

        deleted = delete_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            reason="No longer needed",
        )

        self.assertIsNotNone(deleted["deleted_at"])
        self.assertEqual(deleted["current_version"], 2)

        history = get_history(self.db_path, created["id"], actor_id=self.actor_id)
        self.assertEqual(len(history["events"]), 2)
        self.assertEqual(history["events"][1]["event_type"], "delete")

        with self.assertRaises(AppError) as raised:
            get_document(self.db_path, created["id"], actor_id=self.actor_id)
        self.assertEqual(raised.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)

        assert_replay_matches_latest(self.db_path, created["id"])

    def test_soft_deleted_document_patch_rejected_history_retained(self) -> None:
        created = self._create_document()
        delete_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
        )

        with self.assertRaises(AppError) as raised:
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=2,
                patch=[{"op": "replace", "path": "/learning_rate", "value": 0.1}],
            )

        self.assertEqual(raised.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)
        history = get_history(self.db_path, created["id"], actor_id=self.actor_id)
        self.assertEqual([event["event_type"] for event in history["events"]], ["create", "delete"])

    def test_diff_reports_recursive_changes(self) -> None:
        created = self._create_document()
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=2,
            patch=[{"op": "add", "path": "/optimizer", "value": "adam"}],
        )
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=3,
            patch=[{"op": "remove", "path": "/obsolete"}],
        )

        diff = diff_document_versions(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            from_version=1,
            to_version=4,
        )

        self.assertEqual(diff["from_version"], 1)
        self.assertEqual(diff["to_version"], 4)
        changes_by_path = {change["path"]: change for change in diff["changes"]}
        self.assertEqual(changes_by_path["/learning_rate"]["change_type"], "modified")
        self.assertEqual(changes_by_path["/learning_rate"]["before"], 0.001)
        self.assertEqual(changes_by_path["/learning_rate"]["after"], 0.0005)
        self.assertEqual(changes_by_path["/optimizer"]["change_type"], "added")
        self.assertEqual(changes_by_path["/obsolete"]["change_type"], "removed")

    def test_diff_reports_nested_and_array_value_changes(self) -> None:
        created = self._create_custom_document({"nested": {"value": 1}, "items": [{"name": "a"}, {"name": "b"}]})
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[
                {"op": "replace", "path": "/nested/value", "value": 2},
                {"op": "replace", "path": "/items/1/name", "value": "b2"},
            ],
        )

        diff = diff_document_versions(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            from_version=1,
            to_version=2,
        )

        changes = {change["path"]: change for change in diff["changes"]}
        self.assertEqual(changes["/nested/value"]["change_type"], "modified")
        self.assertEqual(changes["/items/1/name"]["change_type"], "modified")

    def test_diff_after_rollback_and_invalid_version_policy(self) -> None:
        created = self._create_document()
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )
        rollback_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=2,
            target_version=1,
        )

        diff = diff_document_versions(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            from_version=2,
            to_version=3,
        )
        changes = {change["path"]: change for change in diff["changes"]}
        self.assertEqual(changes["/learning_rate"]["before"], 0.0005)
        self.assertEqual(changes["/learning_rate"]["after"], 0.001)

        with self.assertRaises(AppError) as missing_version:
            diff_document_versions(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                from_version=1,
                to_version=99,
            )
        self.assertEqual(missing_version.exception.code, ErrorCode.DOCUMENT_VERSION_NOT_FOUND)

        with self.assertRaises(AppError) as bad_range:
            diff_document_versions(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                from_version=3,
                to_version=1,
            )
        self.assertEqual(bad_range.exception.code, ErrorCode.INVALID_VERSION_RANGE)

    def test_versions_increment_by_one_across_patch_and_delete(self) -> None:
        created = self._create_document()
        first_patch = patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )
        second_patch = patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=2,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0001}],
        )
        deleted = delete_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=3,
        )

        self.assertEqual([created["current_version"], first_patch["current_version"], second_patch["current_version"], deleted["current_version"]], [1, 2, 3, 4])
        assert_replay_matches_latest(self.db_path, created["id"])

    def test_replay_handles_create_patch_delete_sequence(self) -> None:
        created = self._create_document()
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )
        delete_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.actor_id,
            base_version=2,
        )

        assert_replay_matches_latest(self.db_path, created["id"])
        replayed = reconstruct_document_at_version(self.db_path, created["id"], 3)
        self.assertEqual(replayed["learning_rate"], 0.0005)

    def test_version_conflict_and_patch_failure_do_not_write_events(self) -> None:
        created = self._create_document()
        before_snapshot = self._current_snapshot(created["id"])

        with self.assertRaises(AppError):
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=0,
                patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
            )
        with self.assertRaises(AppError):
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[{"op": "remove", "path": "/missing"}],
            )

        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"]), before_snapshot)

    def test_event_insert_failure_prevents_snapshot_update(self) -> None:
        created = self._create_document()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO document_events (
                    id, document_id, actor_id, event_type, base_version, result_version,
                    patch, inverse_patch, changed_paths, before_values, after_values,
                    summary, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "evt_conflict",
                    created["id"],
                    self.actor_id,
                    "test_conflict",
                    1,
                    2,
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "conflict",
                    None,
                    utc_now(),
                ),
            )

        with self.assertRaises(AppError) as raised:
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
            )

        self.assertEqual(raised.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(self._current_snapshot(created["id"])["learning_rate"], 0.001)

    def test_snapshot_update_failure_rolls_back_inserted_event(self) -> None:
        created = self._create_document()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TRIGGER fail_snapshot_update
                BEFORE UPDATE OF current_snapshot_json ON json_documents
                BEGIN
                    SELECT RAISE(ABORT, 'forced snapshot update failure');
                END;
                """
            )

        with self.assertRaises(AppError) as raised:
            patch_document(
                self.db_path,
                document_id=created["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
            )

        self.assertEqual(raised.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(self._event_count(created["id"]), 1)
        self.assertEqual(self._current_snapshot(created["id"])["learning_rate"], 0.001)

    def test_document_events_table_is_append_only_at_db_level(self) -> None:
        created = self._create_document()
        event_id = get_history(self.db_path, created["id"], actor_id=self.actor_id)["events"][0]["id"]

        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE document_events SET summary = ? WHERE id = ?", ("changed", event_id))
        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM document_events WHERE id = ?", (event_id,))

    def test_error_response_shape_for_app_and_validation_errors(self) -> None:
        app = create_app(self.db_path)

        app_handler = app.exception_handlers[AppError]
        app_response = asyncio.run(
            app_handler(
                None,
                AppError(
                    ErrorCode.VERSION_CONFLICT,
                    "Document version conflict. Please reload the latest version.",
                    {"client_base_version": 1, "server_current_version": 3},
                ),
            )
        )
        app_payload = json.loads(app_response.body)
        self.assertEqual(set(app_payload.keys()), {"error"})
        self.assertEqual(app_payload["error"]["code"], ErrorCode.VERSION_CONFLICT)
        self.assertIn("details", app_payload["error"])

        validation_handler = app.exception_handlers[RequestValidationError]
        validation_response = asyncio.run(
            validation_handler(
                None,
                RequestValidationError(
                    [{"type": "missing", "loc": ("body", "patch"), "msg": "Field required", "input": {}}]
                ),
            )
        )
        validation_payload = json.loads(validation_response.body)
        self.assertEqual(validation_payload["error"]["code"], ErrorCode.INVALID_JSON_SYNTAX)
        self.assertIn("details", validation_payload["error"])

    def test_dev_seed_script_creates_bootstrap_ids(self) -> None:
        other_db = str(Path(self.tmp.name) / "seed.sqlite3")
        result = seed_dev(other_db)

        self.assertEqual(result["actor_id"], "user_dev")
        self.assertEqual(result["editor_actor_id"], "user_dev_editor")
        self.assertEqual(result["reviewer_actor_id"], "user_dev_reviewer")
        self.assertEqual(result["viewer_actor_id"], "user_dev_viewer")
        self.assertEqual(result["workspace_id"], "workspace_dev")
        self.assertEqual(result["project_id"], "project_dev")
        self.assertEqual(result["project_role"], "owner")
        with connect(other_db) as conn:
            self.assertIsNotNone(conn.execute("SELECT id FROM users WHERE id = 'user_dev'").fetchone())
            self.assertIsNotNone(conn.execute("SELECT id FROM users WHERE id = 'user_dev_reviewer'").fetchone())
            self.assertIsNotNone(conn.execute("SELECT id FROM projects WHERE id = 'project_dev'").fetchone())
            member = conn.execute(
                "SELECT role FROM project_members WHERE project_id = 'project_dev' AND user_id = 'user_dev'"
            ).fetchone()
            self.assertEqual(member["role"], "owner")
            reviewer_member = conn.execute(
                "SELECT role FROM project_members WHERE project_id = 'project_dev' AND user_id = 'user_dev_reviewer'"
            ).fetchone()
            self.assertEqual(reviewer_member["role"], "reviewer")

    def test_required_routes_are_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/documents", "POST"), routes)
        self.assertIn(("/projects/{project_id}/documents", "GET"), routes)
        self.assertIn(("/documents/{document_id}", "GET"), routes)
        self.assertIn(("/documents/{document_id}", "PATCH"), routes)
        self.assertIn(("/documents/{document_id}/patch-preview", "POST"), routes)
        self.assertIn(("/documents/{document_id}", "DELETE"), routes)
        self.assertIn(("/documents/{document_id}/restore", "POST"), routes)
        self.assertIn(("/documents/{document_id}/history", "GET"), routes)
        self.assertIn(("/documents/{document_id}/history/{version}", "GET"), routes)
        self.assertIn(("/documents/{document_id}/path-history", "GET"), routes)
        self.assertIn(("/documents/{document_id}/blame", "GET"), routes)
        self.assertIn(("/documents/{document_id}/diff", "GET"), routes)
        self.assertIn(("/documents/{document_id}/rollback", "POST"), routes)


if __name__ == "__main__":
    unittest.main()
