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
    get_document_event_detail,
    get_history,
    patch_document,
    restore_document,
    rollback_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class DocumentEventDetailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
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
        for user, role in ((self.editor, "editor"), (self.viewer, "viewer")):
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

    def _history_by_type(self, document_id: str) -> dict[str, dict]:
        history = get_history(self.db_path, document_id, actor_id=self.owner["id"])
        return {event["event_type"]: event for event in history["events"]}

    def _create_updated_document(self) -> dict:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/model.json",
            content={"learning_rate": 0.001, "optimizer": {"name": "adam"}, "items": [1, 2]},
        )
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.editor["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/learning_rate", "value": 0.0005}],
            reason="Tune learning rate",
        )
        return document

    def _insert_malformed_patch_event(self, *, document_id: str, event_id: str) -> None:
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
                VALUES (?, ?, ?, NULL, 'update', 1, 2, ?, '[]', '[]', '[]', '[]', ?, NULL, ?)
                """,
                (
                    event_id,
                    document_id,
                    self.owner["id"],
                    '{"op":',
                    f"Malformed event detail event {event_id}",
                    "2026-06-28T00:00:00Z",
                ),
            )
            conn.execute(
                """
                UPDATE json_documents
                SET current_version = 2
                WHERE id = ?
                """,
                (document_id,),
            )

    def _create_full_lifecycle_document(self) -> dict:
        document = self._create_updated_document()
        rollback_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=2,
            target_version=1,
            reason="Restore baseline",
        )
        delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=3,
            reason="Archive",
        )
        restore_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=4,
            reason="Restore archive",
        )
        return document

    def test_event_detail_returns_stored_values_without_snapshots_or_mutation(self) -> None:
        document = self._create_updated_document()
        patch_event = self._history_by_type(document["id"])["update"]
        before_event_count = self._event_count()
        before_audit_count = self._audit_count()
        before_snapshot = self._snapshot(document["id"])

        detail = get_document_event_detail(
            self.db_path,
            document_id=document["id"],
            event_id=patch_event["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(detail["document_id"], document["id"])
        self.assertEqual(detail["project_id"], self.project["id"])
        self.assertEqual(detail["full_path"], "config/model.json")
        self.assertEqual(detail["current_version"], 2)
        self.assertIsNone(detail["deleted_at"])
        self.assertEqual(detail["event"]["id"], patch_event["id"])
        self.assertEqual(detail["event"]["event_type"], "update")
        self.assertEqual(detail["event"]["actor_id"], self.editor["id"])
        self.assertEqual(detail["event"]["base_version"], 1)
        self.assertEqual(detail["event"]["result_version"], 2)
        self.assertEqual(detail["event"]["patch"], [{"op": "replace", "path": "/learning_rate", "value": 0.0005}])
        self.assertEqual(detail["event"]["inverse_patch"], [{"op": "replace", "path": "/learning_rate", "value": 0.001}])
        self.assertEqual(detail["event"]["changed_paths"], ["/learning_rate"])
        self.assertEqual(detail["event"]["before_values"], [{"path": "/learning_rate", "exists": True, "value": 0.001}])
        self.assertEqual(detail["event"]["after_values"], [{"path": "/learning_rate", "exists": True, "value": 0.0005}])
        self.assertEqual(detail["event"]["reason"], "Tune learning rate")
        self.assertEqual(detail["snapshots"], {"included": False, "before": None, "after": None})
        self.assertNotIn("content", detail)
        self.assertEqual(self._event_count(), before_event_count)
        self.assertEqual(self._audit_count(), before_audit_count)
        self.assertEqual(self._snapshot(document["id"]), before_snapshot)

    def test_event_detail_reports_malformed_event_json_without_snapshots(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/malformed-event-detail.json",
            content={"value": 1},
        )
        self._insert_malformed_patch_event(document_id=document["id"], event_id="evt_detail_bad_json")

        detail = get_document_event_detail(
            self.db_path,
            document_id=document["id"],
            event_id="evt_detail_bad_json",
            actor_id=self.owner["id"],
        )

        self.assertEqual(detail["event"]["id"], "evt_detail_bad_json")
        self.assertIsNone(detail["event"]["patch"])
        self.assertEqual(detail["event"]["json_errors"][0]["field"], "patch")
        self.assertEqual(detail["event"]["json_errors"][0]["message"], "Expecting value")
        self.assertEqual(detail["snapshots"], {"included": False, "before": None, "after": None})

    def test_http_event_detail_reports_malformed_event_json_snapshot_error(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/http-malformed-event-detail.json",
            content={"value": 1},
        )
        self._insert_malformed_patch_event(document_id=document["id"], event_id="evt_detail_http_bad_json")
        client = TestClient(create_app(self.db_path))

        response = client.get(
            f"/documents/{document['id']}/events/evt_detail_http_bad_json",
            headers={"X-Actor-Id": self.owner["id"]},
            params={"include_snapshots": "true"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["event"]["id"], "evt_detail_http_bad_json")
        self.assertIsNone(body["event"]["patch"])
        self.assertEqual(body["event"]["json_errors"][0]["field"], "patch")
        self.assertTrue(body["snapshots"]["included"])
        self.assertIsNone(body["snapshots"]["before"])
        self.assertIsNone(body["snapshots"]["after"])
        self.assertEqual(body["snapshots"]["error"]["code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(body["snapshots"]["error"]["details"]["failures"][0]["field"], "patch")

    def test_include_snapshots_reconstructs_create_update_delete_rollback_and_restore_events(self) -> None:
        document = self._create_full_lifecycle_document()
        history = self._history_by_type(document["id"])
        initial = {"learning_rate": 0.001, "optimizer": {"name": "adam"}, "items": [1, 2]}
        updated = {"learning_rate": 0.0005, "optimizer": {"name": "adam"}, "items": [1, 2]}

        create_detail = get_document_event_detail(
            self.db_path,
            document_id=document["id"],
            event_id=history["create"]["id"],
            actor_id=self.owner["id"],
            include_snapshots=True,
        )
        update_detail = get_document_event_detail(
            self.db_path,
            document_id=document["id"],
            event_id=history["update"]["id"],
            actor_id=self.owner["id"],
            include_snapshots=True,
        )
        rollback_detail = get_document_event_detail(
            self.db_path,
            document_id=document["id"],
            event_id=history["rollback"]["id"],
            actor_id=self.owner["id"],
            include_snapshots=True,
        )
        delete_detail = get_document_event_detail(
            self.db_path,
            document_id=document["id"],
            event_id=history["delete"]["id"],
            actor_id=self.owner["id"],
            include_snapshots=True,
        )
        restore_detail = get_document_event_detail(
            self.db_path,
            document_id=document["id"],
            event_id=history["restore"]["id"],
            actor_id=self.owner["id"],
            include_snapshots=True,
        )

        self.assertEqual(create_detail["snapshots"], {"included": True, "before": None, "after": initial})
        self.assertEqual(update_detail["snapshots"], {"included": True, "before": initial, "after": updated})
        self.assertEqual(rollback_detail["snapshots"], {"included": True, "before": updated, "after": initial})
        self.assertEqual(delete_detail["snapshots"], {"included": True, "before": initial, "after": initial})
        self.assertEqual(restore_detail["snapshots"], {"included": True, "before": initial, "after": initial})
        self.assertEqual([history[key]["result_version"] for key in ("create", "update", "rollback", "delete", "restore")], [1, 2, 3, 4, 5])
        assert_replay_matches_latest(self.db_path, document["id"])

    def test_soft_deleted_document_event_detail_remains_readable(self) -> None:
        document = self._create_updated_document()
        deleted = delete_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.owner["id"],
            base_version=2,
        )
        delete_event = self._history_by_type(document["id"])["delete"]

        owner_detail = get_document_event_detail(
            self.db_path,
            document_id=document["id"],
            event_id=delete_event["id"],
            actor_id=self.owner["id"],
        )
        viewer_detail = get_document_event_detail(
            self.db_path,
            document_id=document["id"],
            event_id=delete_event["id"],
            actor_id=self.viewer["id"],
        )

        self.assertEqual(owner_detail["deleted_at"], deleted["deleted_at"])
        self.assertEqual(viewer_detail["event"]["id"], delete_event["id"])
        self.assertEqual(viewer_detail["event"]["event_type"], "delete")

    def test_event_detail_permission_and_document_boundary_policy(self) -> None:
        document = self._create_updated_document()
        event = self._history_by_type(document["id"])["update"]
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )
        other_event = get_history(self.db_path, other_document["id"], actor_id=self.owner["id"])["events"][0]

        viewer_detail = get_document_event_detail(
            self.db_path,
            document_id=document["id"],
            event_id=event["id"],
            actor_id=self.viewer["id"],
        )
        self.assertEqual(viewer_detail["event"]["id"], event["id"])

        with self.assertRaises(AppError) as missing_actor:
            get_document_event_detail(
                self.db_path,
                document_id=document["id"],
                event_id=event["id"],
                actor_id=None,
            )
        self.assertEqual(missing_actor.exception.code, ErrorCode.AUTH_REQUIRED)

        with self.assertRaises(AppError) as nonmember:
            get_document_event_detail(
                self.db_path,
                document_id=document["id"],
                event_id=event["id"],
                actor_id=self.nonmember["id"],
            )
        self.assertEqual(nonmember.exception.code, ErrorCode.PERMISSION_DENIED)

        with self.assertRaises(AppError) as wrong_document:
            get_document_event_detail(
                self.db_path,
                document_id=document["id"],
                event_id=other_event["id"],
                actor_id=self.owner["id"],
            )
        self.assertEqual(wrong_document.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)
        self.assertEqual(wrong_document.exception.details["document_id"], document["id"])
        self.assertEqual(wrong_document.exception.details["event_id"], other_event["id"])

        with self.assertRaises(AppError) as missing_event:
            get_document_event_detail(
                self.db_path,
                document_id=document["id"],
                event_id="evt_missing",
                actor_id=self.owner["id"],
            )
        self.assertEqual(missing_event.exception.code, ErrorCode.DOCUMENT_NOT_FOUND)

    def test_http_route_and_project_scoped_api_token_scope(self) -> None:
        document = self._create_updated_document()
        event = self._history_by_type(document["id"])["update"]
        other_document = create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )
        other_event = get_history(self.db_path, other_document["id"], actor_id=self.owner["id"])["events"][0]
        client = TestClient(create_app(self.db_path))
        token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.owner["id"]},
            json={"name": "event detail token"},
        )
        self.assertEqual(token_response.status_code, 200)
        token = token_response.json()["token"]

        response = client.get(
            f"/documents/{document['id']}/events/{event['id']}",
            headers={"Authorization": f"Bearer {token}"},
            params={"include_snapshots": "true"},
        )
        other_response = client.get(
            f"/documents/{other_document['id']}/events/{other_event['id']}",
            headers={"Authorization": f"Bearer {token}"},
            params={"include_snapshots": "true"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["document_id"], document["id"])
        self.assertEqual(body["event"]["id"], event["id"])
        self.assertTrue(body["snapshots"]["included"])
        self.assertEqual(body["snapshots"]["before"]["learning_rate"], 0.001)
        self.assertEqual(body["snapshots"]["after"]["learning_rate"], 0.0005)
        self.assertEqual(other_response.status_code, 403)
        self.assertEqual(other_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

    def test_document_event_detail_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/documents/{document_id}/events/{event_id}", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
