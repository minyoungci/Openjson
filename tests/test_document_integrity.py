from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import create_document, delete_document, patch_document, restore_document, rollback_document
from app.errors import AppError, ErrorCode
from app.integrity_service import check_document_replay_integrity
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class DocumentReplayIntegrityTests(unittest.TestCase):
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

    def _event_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]

    def _audit_count(self) -> int:
        with connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) AS count FROM audit_log").fetchone()["count"]

    def _snapshot(self, document_id: str) -> object:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        return json.loads(row["current_snapshot_json"])

    def _create_changed_document(self, full_path: str = "config/model.json") -> dict:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path=full_path,
            content={"value": 1, "items": [1]},
        )
        patched = patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.editor["id"],
            base_version=1,
            patch=[
                {"op": "replace", "path": "/value", "value": 2},
                {"op": "add", "path": "/items/1", "value": 2},
            ],
        )
        rollback_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=patched["current_version"],
            target_version=1,
        )
        return document

    def test_document_integrity_reports_ok_for_patch_rollback_delete_restore_without_mutation(self) -> None:
        document = self._create_changed_document()
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=3,
        )
        restore_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=4,
        )
        before_events = self._event_count()
        before_audit = self._audit_count()
        before_snapshot = self._snapshot(document["id"])

        result = check_document_replay_integrity(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(result["document_id"], document["id"])
        self.assertEqual(result["project_id"], self.project["id"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["document"]["document_id"], document["id"])
        self.assertEqual(result["document"]["current_version"], 5)
        self.assertEqual(result["document"]["latest_event_version"], 5)
        self.assertEqual(result["document"]["event_count"], 5)
        self.assertEqual(result["document"]["status"], "ok")
        self.assertEqual(result["document"]["replay_matches_latest"], True)
        self.assertIsNone(result["document"]["deleted_at"])
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._audit_count(), before_audit)
        self.assertEqual(self._snapshot(document["id"]), before_snapshot)

    def test_soft_deleted_document_integrity_remains_checkable(self) -> None:
        document = self._create_changed_document()
        deleted = delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=3,
        )

        result = check_document_replay_integrity(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["document"]["current_version"], 4)
        self.assertEqual(result["document"]["latest_event_version"], 4)
        self.assertEqual(result["document"]["event_count"], 4)
        self.assertEqual(result["document"]["deleted_at"], deleted["deleted_at"])

    def test_document_integrity_detects_snapshot_and_version_tampering(self) -> None:
        snapshot_tampered = self._create_changed_document("config/snapshot.json")
        version_tampered = self._create_changed_document("config/version.json")
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_snapshot_json = ?
                WHERE id = ?
                """,
                (json.dumps({"tampered": True}, separators=(",", ":")), snapshot_tampered["id"]),
            )
            conn.execute(
                """
                UPDATE json_documents
                SET current_version = ?
                WHERE id = ?
                """,
                (99, version_tampered["id"]),
            )

        snapshot_result = check_document_replay_integrity(
            self.db_path,
            document_id=snapshot_tampered["id"],
            actor_id=self.owner["id"],
        )
        version_result = check_document_replay_integrity(
            self.db_path,
            document_id=version_tampered["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(snapshot_result["status"], "failed")
        self.assertEqual(snapshot_result["failure_count"], 1)
        self.assertEqual(snapshot_result["document"]["error_code"], "SNAPSHOT_REPLAY_MISMATCH")
        self.assertEqual(snapshot_result["failures"][0]["document_id"], snapshot_tampered["id"])
        self.assertEqual(version_result["status"], "failed")
        self.assertEqual(version_result["failure_count"], 1)
        self.assertEqual(version_result["document"]["error_code"], "VERSION_MISMATCH")
        self.assertEqual(version_result["document"]["current_version"], 99)
        self.assertEqual(version_result["document"]["latest_event_version"], 3)

    def test_document_integrity_permission_and_missing_document_policy(self) -> None:
        document = self._create_changed_document()
        for actor, allowed in (
            (self.owner, True),
            (self.admin, True),
            (self.editor, False),
            (self.viewer, False),
            (self.nonmember, False),
        ):
            if allowed:
                result = check_document_replay_integrity(
                    self.db_path,
                    document_id=document["id"],
                    actor_id=actor["id"],
                )
                self.assertEqual(result["status"], "ok")
            else:
                with self.assertRaises(AppError) as denied:
                    check_document_replay_integrity(
                        self.db_path,
                        document_id=document["id"],
                        actor_id=actor["id"],
                    )
                self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as missing_actor:
            check_document_replay_integrity(
                self.db_path,
                document_id=document["id"],
                actor_id=None,
            )
        self.assertEqual(missing_actor.exception.code, ErrorCode.AUTH_REQUIRED)

        with self.assertRaises(AppError) as missing_document:
            check_document_replay_integrity(
                self.db_path,
                document_id="doc_missing",
                actor_id=self.owner["id"],
            )
        self.assertEqual(missing_document.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)

    def test_http_route_and_project_scoped_api_token_scope(self) -> None:
        document = self._create_changed_document()
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )
        client = TestClient(create_app(self.db_path))
        owner_token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "document integrity token"},
        )
        viewer_token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.viewer["id"]},
            json={"name": "viewer document integrity token"},
        )
        self.assertEqual(owner_token_response.status_code, 200)
        self.assertEqual(viewer_token_response.status_code, 200)
        owner_token = owner_token_response.json()["token"]
        viewer_token = viewer_token_response.json()["token"]

        checked = client.get(
            f"/documents/{document['id']}/integrity/replay",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        other_project_check = client.get(
            f"/documents/{other_document['id']}/integrity/replay",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        viewer_check = client.get(
            f"/documents/{document['id']}/integrity/replay",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        missing_actor = client.get(f"/documents/{document['id']}/integrity/replay")

        self.assertEqual(checked.status_code, 200)
        self.assertEqual(checked.json()["status"], "ok")
        self.assertEqual(checked.json()["document"]["document_id"], document["id"])
        self.assertEqual(checked.json()["document"]["replay_matches_latest"], True)
        self.assertEqual(other_project_check.status_code, 403)
        self.assertEqual(other_project_check.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(viewer_check.status_code, 403)
        self.assertEqual(viewer_check.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(missing_actor.status_code, 401)
        self.assertEqual(missing_actor.json()["error"]["code"], ErrorCode.AUTH_REQUIRED)

    def test_document_integrity_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/documents/{document_id}/integrity/replay", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
