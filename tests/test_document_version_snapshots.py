from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import (
    create_document,
    delete_document,
    get_document_version,
    patch_document,
    restore_document,
    rollback_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class DocumentVersionSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
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
        add_project_member(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            user_id=self.viewer["id"],
            role="viewer",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_document(self) -> dict:
        return create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/model.json",
            content={"model": "baseline", "learning_rate": 0.001, "obsolete": True},
        )

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _current_snapshot(self, document_id: str) -> object:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT current_snapshot_json FROM json_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        return json.loads(row["current_snapshot_json"])

    def test_version_snapshot_reconstructs_create_patch_and_rollback_versions(self) -> None:
        created = self._create_document()
        patch_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
        )
        rollback_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            base_version=2,
            target_version=1,
        )
        before_event_count = self._event_count(created["id"])
        before_latest_snapshot = self._current_snapshot(created["id"])

        version_one = get_document_version(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            version=1,
        )
        version_two = get_document_version(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            version=2,
        )
        version_three = get_document_version(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            version=3,
        )

        self.assertEqual(version_one["content"]["learning_rate"], 0.001)
        self.assertEqual(version_one["event"]["event_type"], "create")
        self.assertFalse(version_one["is_latest"])
        self.assertEqual(version_two["content"]["learning_rate"], 0.0005)
        self.assertEqual(version_two["event"]["event_type"], "update")
        self.assertEqual(version_three["content"]["learning_rate"], 0.001)
        self.assertEqual(version_three["event"]["event_type"], "rollback")
        self.assertTrue(version_three["is_latest"])
        self.assertEqual(self._event_count(created["id"]), before_event_count)
        self.assertEqual(self._current_snapshot(created["id"]), before_latest_snapshot)

    def test_soft_deleted_and_restored_document_version_snapshots_are_retained(self) -> None:
        created = self._create_document()
        delete_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )
        restore_document(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            base_version=2,
        )

        created_version = get_document_version(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            version=1,
        )
        delete_version = get_document_version(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            version=2,
        )
        restore_version = get_document_version(
            self.db_path,
            document_id=created["id"],
            actor_id=self.owner["id"],
            version=3,
        )

        self.assertEqual(created_version["event"]["event_type"], "create")
        self.assertIsNone(created_version["deleted_at"])
        self.assertEqual(delete_version["event"]["event_type"], "delete")
        self.assertEqual(delete_version["content"], created["content"])
        self.assertFalse(delete_version["is_latest"])
        self.assertEqual(restore_version["event"]["event_type"], "restore")
        self.assertEqual(restore_version["content"], created["content"])
        self.assertTrue(restore_version["is_latest"])

    def test_missing_invalid_and_permission_errors(self) -> None:
        created = self._create_document()

        viewer_read = get_document_version(
            self.db_path,
            document_id=created["id"],
            actor_id=self.viewer["id"],
            version=1,
        )
        self.assertEqual(viewer_read["version"], 1)

        with self.assertRaises(AppError) as invalid_version:
            get_document_version(
                self.db_path,
                document_id=created["id"],
                actor_id=self.owner["id"],
                version=0,
            )
        self.assertEqual(invalid_version.exception.code, ErrorCode.INVALID_VERSION_RANGE)

        with self.assertRaises(AppError) as missing_version:
            get_document_version(
                self.db_path,
                document_id=created["id"],
                actor_id=self.owner["id"],
                version=99,
            )
        self.assertEqual(missing_version.exception.code, ErrorCode.DOCUMENT_VERSION_NOT_FOUND)

        with self.assertRaises(AppError) as nonmember:
            get_document_version(
                self.db_path,
                document_id=created["id"],
                actor_id=self.nonmember["id"],
                version=1,
            )
        self.assertEqual(nonmember.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_http_route_and_project_scoped_api_token_policy(self) -> None:
        document = self._create_document()
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )
        client = TestClient(create_app(self.db_path))
        token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "history version token"},
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]

        version_response = client.get(
            f"/documents/{document['id']}/history/1",
            headers={"Authorization": f"Bearer {token}"},
        )
        other_response = client.get(
            f"/documents/{other_document['id']}/history/1",
            headers={"Authorization": f"Bearer {token}"},
        )
        missing_version_response = client.get(
            f"/documents/{document['id']}/history/99",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(version_response.status_code, 200)
        self.assertEqual(version_response.json()["content"], document["content"])
        self.assertEqual(version_response.json()["event"]["event_type"], "create")
        self.assertEqual(other_response.status_code, 403)
        self.assertEqual(other_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(missing_version_response.status_code, 404)
        self.assertEqual(missing_version_response.json()["error"]["code"], ErrorCode.DOCUMENT_VERSION_NOT_FOUND)

    def test_document_version_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/documents/{document_id}/history/{version}", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
