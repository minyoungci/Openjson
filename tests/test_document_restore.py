from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import (
    assert_replay_matches_latest,
    create_document,
    delete_document,
    get_document,
    get_history,
    list_project_documents,
    restore_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class DocumentRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.admin = create_user(self.db_path, email="admin@example.com", display_name="Admin")
        self.editor = create_user(self.db_path, email="editor@example.com", display_name="Editor")
        self.viewer = create_user(self.db_path, email="viewer@example.com", display_name="Viewer")
        self.nonmember = create_user(self.db_path, email="outside@example.com", display_name="Outside")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )
        self.other_project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Other Project",
        )
        for user, role in ((self.admin, "admin"), (self.editor, "editor"), (self.viewer, "viewer")):
            add_project_member(
                self.db_path,
                project_id=self.project["id"],
                actor_id=self.owner["id"],
                user_id=user["id"],
                role=role,
            )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_document(self, full_path: str = "config/model.json") -> dict:
        return create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path=full_path,
            content={"model": "baseline", "learning_rate": 0.001},
        )

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _deleted_at(self, document_id: str) -> str | None:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT deleted_at FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()["deleted_at"]

    def _current_version(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT current_version FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()["current_version"]

    def _current_snapshot(self, document_id: str) -> object:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        return json.loads(row["current_snapshot_json"])

    def test_restore_creates_event_clears_deleted_at_and_preserves_replay(self) -> None:
        document = self._create_document()
        deleted = delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )
        self.assertIsNotNone(deleted["deleted_at"])
        hidden = list_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        self.assertEqual(hidden["documents"], [])

        restored = restore_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=2,
            reason="Undo accidental delete",
        )

        self.assertEqual(restored["previous_version"], 2)
        self.assertEqual(restored["current_version"], 3)
        self.assertIsNone(restored["deleted_at"])
        self.assertEqual(restored["content"], document["content"])
        self.assertTrue(restored["validation"]["valid"])
        self.assertEqual(get_document(self.db_path, document["id"], actor_id=self.owner["id"])["content"], document["content"])
        visible = list_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        self.assertEqual([row["id"] for row in visible["documents"]], [document["id"]])
        history = get_history(self.db_path, document["id"], actor_id=self.owner["id"])
        self.assertEqual([event["event_type"] for event in history["events"]], ["create", "delete", "restore"])
        self.assertEqual(history["events"][2]["base_version"], 2)
        self.assertEqual(history["events"][2]["result_version"], 3)
        self.assertEqual(history["events"][2]["reason"], "Undo accidental delete")
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_delete_and_restore_events_preserve_lifecycle_metadata(self) -> None:
        document = self._create_document()
        expected_root_record = {"path": "", "exists": True, "value": document["content"]}
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
            reason="Archive stale config",
        )
        restore_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=2,
            reason="Restore archived config",
        )

        history = get_history(self.db_path, document["id"], actor_id=self.owner["id"])
        delete_event = history["events"][1]
        restore_event = history["events"][2]

        self.assertEqual(delete_event["event_type"], "delete")
        self.assertEqual(delete_event["patch"], [])
        self.assertEqual(delete_event["inverse_patch"], [])
        self.assertEqual(delete_event["changed_paths"], [])
        self.assertEqual(delete_event["before_values"], [expected_root_record])
        self.assertEqual(delete_event["after_values"], [expected_root_record])
        self.assertEqual(delete_event["validation_schema_id"], None)
        self.assertEqual(delete_event["reason"], "Archive stale config")

        self.assertEqual(restore_event["event_type"], "restore")
        self.assertEqual(restore_event["patch"], [])
        self.assertEqual(restore_event["inverse_patch"], [])
        self.assertEqual(restore_event["changed_paths"], [])
        self.assertEqual(restore_event["before_values"], [expected_root_record])
        self.assertEqual(restore_event["after_values"], [expected_root_record])
        self.assertEqual(restore_event["validation_schema_id"], None)
        self.assertEqual(restore_event["reason"], "Restore archived config")
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_restore_rejects_wrong_base_active_document_and_path_conflict_without_event(self) -> None:
        document = self._create_document()
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )
        with self.assertRaises(AppError) as wrong_base:
            restore_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                base_version=1,
            )
        self.assertEqual(wrong_base.exception.code, ErrorCode.VERSION_CONFLICT)
        self.assertEqual(self._event_count(document["id"]), 2)
        self.assertIsNotNone(self._deleted_at(document["id"]))

        restored = restore_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=2,
        )
        with self.assertRaises(AppError) as active_restore:
            restore_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                base_version=restored["current_version"],
            )
        self.assertEqual(active_restore.exception.code, ErrorCode.INVALID_REQUEST)
        self.assertEqual(self._event_count(document["id"]), 3)

        conflicting_deleted = self._create_document(full_path="config/conflict.json")
        delete_document(
            self.db_path,
            document_id=conflicting_deleted["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )
        create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/conflict.json",
            content={"replacement": True},
        )
        before_snapshot = self._current_snapshot(conflicting_deleted["id"])
        with self.assertRaises(AppError) as conflict:
            restore_document(
                self.db_path,
                document_id=conflicting_deleted["id"],
                actor_id=self.owner["id"],
                base_version=2,
            )
        self.assertEqual(conflict.exception.code, ErrorCode.PATCH_APPLY_FAILED)
        self.assertEqual(self._event_count(conflicting_deleted["id"]), 2)
        self.assertEqual(self._current_version(conflicting_deleted["id"]), 2)
        self.assertIsNotNone(self._deleted_at(conflicting_deleted["id"]))
        self.assertEqual(self._current_snapshot(conflicting_deleted["id"]), before_snapshot)

    def test_restore_permission_policy_owner_admin_only(self) -> None:
        for actor, expected in ((self.owner, True), (self.admin, True), (self.editor, False), (self.viewer, False), (self.nonmember, False)):
            document = self._create_document(full_path=f"config/{actor['id']}.json")
            delete_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.owner["id"],
                base_version=1,
            )
            if expected:
                restored = restore_document(
                    self.db_path,
                    document_id=document["id"],
                    actor_id=actor["id"],
                    base_version=2,
                )
                self.assertIsNone(restored["deleted_at"])
                self.assertEqual(restored["current_version"], 3)
            else:
                with self.assertRaises(AppError) as denied:
                    restore_document(
                        self.db_path,
                        document_id=document["id"],
                        actor_id=actor["id"],
                        base_version=2,
                    )
                self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)
                self.assertEqual(self._event_count(document["id"]), 2)
                self.assertIsNotNone(self._deleted_at(document["id"]))

    def test_http_restore_route_and_api_token_scope(self) -> None:
        document = self._create_document()
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )
        delete_document(
            self.db_path,
            document_id=other_document["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )
        client = TestClient(create_app(self.db_path))
        token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "restore token"},
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]

        restored = client.post(
            f"/documents/{document['id']}/restore",
            headers={"Authorization": f"Bearer {token}"},
            json={"base_version": 2, "reason": "HTTP restore"},
        )
        other_restore = client.post(
            f"/documents/{other_document['id']}/restore",
            headers={"Authorization": f"Bearer {token}"},
            json={"base_version": 2},
        )

        self.assertEqual(restored.status_code, 200)
        self.assertIsNone(restored.json()["deleted_at"])
        self.assertEqual(restored.json()["current_version"], 3)
        self.assertEqual(other_restore.status_code, 403)
        self.assertEqual(other_restore.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

    def test_restore_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/documents/{document_id}/restore", "POST"), routes)


if __name__ == "__main__":
    unittest.main()
