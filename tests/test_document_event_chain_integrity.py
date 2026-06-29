from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import create_document, delete_document, patch_document, restore_document, rollback_document
from app.errors import AppError, ErrorCode
from app.integrity_service import check_document_event_chain_integrity
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class DocumentEventChainIntegrityTests(unittest.TestCase):
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

    def _insert_event(
        self,
        *,
        document_id: str,
        event_id: str,
        event_type: str,
        base_version: int,
        result_version: int,
        patch: list[dict],
        inverse_patch: list[dict],
        changed_paths: list[str],
        before_values: list[dict],
        after_values: list[dict],
    ) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO document_events (
                    id,
                    document_id,
                    actor_id,
                    validation_schema_id,
                    event_type,
                    base_version,
                    result_version,
                    patch,
                    inverse_patch,
                    changed_paths,
                    before_values,
                    after_values,
                    summary,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    event_id,
                    document_id,
                    self.owner["id"],
                    event_type,
                    base_version,
                    result_version,
                    json.dumps(patch, separators=(",", ":")),
                    json.dumps(inverse_patch, separators=(",", ":")),
                    json.dumps(changed_paths, separators=(",", ":")),
                    json.dumps(before_values, separators=(",", ":")),
                    json.dumps(after_values, separators=(",", ":")),
                    f"Tampered event {event_id}",
                    "2026-06-27T00:00:00Z",
                ),
            )

    def test_event_chain_integrity_reports_ok_for_patch_rollback_delete_restore_without_mutation(self) -> None:
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

        result = check_document_event_chain_integrity(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(result["document_id"], document["id"])
        self.assertEqual(result["project_id"], self.project["id"])
        self.assertEqual(result["full_path"], "config/model.json")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["current_version"], 5)
        self.assertEqual(result["latest_event_version"], 5)
        self.assertEqual(result["event_count"], 5)
        self.assertEqual(result["checked_events"], 5)
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(result["checks"], {
            "version_chain": "ok",
            "event_types": "ok",
            "event_metadata": "ok",
            "replay_matches_latest": "ok",
        })
        self.assertEqual(result["failures"], [])
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._audit_count(), before_audit)
        self.assertEqual(self._snapshot(document["id"]), before_snapshot)

    def test_soft_deleted_document_event_chain_remains_checkable(self) -> None:
        document = self._create_changed_document()
        deleted = delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=3,
        )

        result = check_document_event_chain_integrity(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["current_version"], 4)
        self.assertEqual(result["latest_event_version"], 4)
        self.assertEqual(result["event_count"], 4)
        self.assertEqual(result["deleted_at"], deleted["deleted_at"])

    def test_event_chain_reports_version_gap(self) -> None:
        document = self._create_changed_document()
        snapshot = self._snapshot(document["id"])
        root_record = [{"path": "", "exists": True, "value": snapshot}]
        self._insert_event(
            document_id=document["id"],
            event_id="evt_gap",
            event_type="restore",
            base_version=3,
            result_version=5,
            patch=[],
            inverse_patch=[],
            changed_paths=[],
            before_values=root_record,
            after_values=root_record,
        )

        result = check_document_event_chain_integrity(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["checks"]["version_chain"], "failed")
        self.assertIn("EVENT_RESULT_VERSION_MISMATCH", {failure["error_code"] for failure in result["failures"]})

    def test_event_chain_reports_metadata_mismatch_even_when_final_replay_matches_latest(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/metadata.json",
            content={"value": 1},
        )
        self._insert_event(
            document_id=document["id"],
            event_id="evt_bad_metadata",
            event_type="update",
            base_version=1,
            result_version=2,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
            inverse_patch=[{"op": "replace", "path": "/value", "value": 1}],
            changed_paths=["/value"],
            before_values=[{"path": "/value", "exists": True, "value": 999}],
            after_values=[{"path": "/value", "exists": True, "value": 2}],
        )
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_version = 2,
                    current_snapshot_json = ?
                WHERE id = ?
                """,
                (json.dumps({"value": 2}, separators=(",", ":")), document["id"]),
            )

        result = check_document_event_chain_integrity(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["checks"]["event_metadata"], "failed")
        self.assertEqual(result["checks"]["replay_matches_latest"], "ok")
        failures = {failure["error_code"]: failure for failure in result["failures"]}
        self.assertIn("EVENT_BEFORE_VALUES_MISMATCH", failures)
        self.assertEqual(failures["EVENT_BEFORE_VALUES_MISMATCH"]["event_id"], "evt_bad_metadata")

    def test_event_chain_reports_snapshot_replay_mismatch(self) -> None:
        document = self._create_changed_document()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_snapshot_json = ?
                WHERE id = ?
                """,
                (json.dumps({"tampered": True}, separators=(",", ":")), document["id"]),
            )

        result = check_document_event_chain_integrity(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["checks"]["replay_matches_latest"], "failed")
        self.assertIn("EVENT_CHAIN_REPLAY_MISMATCH", {failure["error_code"] for failure in result["failures"]})

    def test_event_chain_permission_and_missing_document_policy(self) -> None:
        document = self._create_changed_document()
        for actor, allowed in (
            (self.owner, True),
            (self.admin, True),
            (self.editor, False),
            (self.viewer, False),
            (self.nonmember, False),
        ):
            if allowed:
                result = check_document_event_chain_integrity(
                    self.db_path,
                    document_id=document["id"],
                    actor_id=actor["id"],
                )
                self.assertEqual(result["status"], "ok")
            else:
                with self.assertRaises(AppError) as denied:
                    check_document_event_chain_integrity(
                        self.db_path,
                        document_id=document["id"],
                        actor_id=actor["id"],
                    )
                self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as missing_actor:
            check_document_event_chain_integrity(
                self.db_path,
                document_id=document["id"],
                actor_id=None,
            )
        self.assertEqual(missing_actor.exception.code, ErrorCode.AUTH_REQUIRED)

        with self.assertRaises(AppError) as missing_document:
            check_document_event_chain_integrity(
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
            json={"name": "event chain integrity token"},
        )
        viewer_token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.viewer["id"]},
            json={"name": "viewer event chain integrity token"},
        )
        self.assertEqual(owner_token_response.status_code, 200)
        self.assertEqual(viewer_token_response.status_code, 200)
        owner_token = owner_token_response.json()["token"]
        viewer_token = viewer_token_response.json()["token"]

        checked = client.get(
            f"/documents/{document['id']}/integrity/events",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        other_project_check = client.get(
            f"/documents/{other_document['id']}/integrity/events",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        viewer_check = client.get(
            f"/documents/{document['id']}/integrity/events",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )

        self.assertEqual(checked.status_code, 200)
        self.assertEqual(checked.json()["status"], "ok")
        self.assertEqual(checked.json()["document_id"], document["id"])
        self.assertEqual(checked.json()["checks"]["event_metadata"], "ok")
        self.assertEqual(other_project_check.status_code, 403)
        self.assertEqual(other_project_check.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(viewer_check.status_code, 403)
        self.assertEqual(viewer_check.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

    def test_document_event_chain_integrity_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/documents/{document_id}/integrity/events", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
