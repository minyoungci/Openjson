from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.comment_service import create_comment_thread
from app.database import connect, init_db
from app.document_service import create_document, delete_document, patch_document
from app.errors import AppError, ErrorCode
from app.export_service import FORMAT_VERSION, export_project_archive
from app.main import create_app
from app.review_service import create_review_request
from app.schema_service import create_schema
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class ProjectExportTests(unittest.TestCase):
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
                    f"Tampered export event {event_id}",
                    "2026-06-28T00:00:00Z",
                ),
            )

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
                    f"Malformed export event {event_id}",
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

    def _create_schema_and_document(self) -> tuple[dict, dict]:
        schema = create_schema(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name="model-config",
            version="1",
            schema_json={
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "number"}},
                "additionalProperties": True,
            },
            file_pattern="config/*.json",
        )
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/model.json",
            content={"value": 1, "label": "baseline"},
        )
        patch_document(
            self.db_path,
            document_id=document["id"],
            actor_id=self.editor["id"],
            base_version=1,
            patch=[{"op": "replace", "path": "/value", "value": 2}],
            reason="Update exported value",
        )
        return schema, document

    def test_export_includes_metadata_schemas_snapshots_events_and_integrity_without_mutation(self) -> None:
        schema, document = self._create_schema_and_document()
        before_events = self._event_count()
        before_audit = self._audit_count()

        archive = export_project_archive(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(archive["format_version"], FORMAT_VERSION)
        self.assertEqual(archive["project"]["id"], self.project["id"])
        self.assertEqual(archive["workspace"]["id"], self.workspace["id"])
        self.assertEqual({member["role"] for member in archive["members"]}, {"owner", "admin", "editor", "viewer"})
        self.assertEqual(archive["schemas"][0]["id"], schema["id"])
        self.assertEqual(archive["schemas"][0]["schema"]["required"], ["value"])
        self.assertEqual(len(archive["documents"]), 1)
        exported_document = archive["documents"][0]
        self.assertEqual(exported_document["id"], document["id"])
        self.assertEqual(exported_document["schema_id"], schema["id"])
        self.assertEqual(exported_document["content"], {"value": 2, "label": "baseline"})
        self.assertEqual([event["event_type"] for event in exported_document["events"]], ["create", "update"])
        self.assertEqual(exported_document["events"][1]["reason"], "Update exported value")
        self.assertEqual(archive["integrity"]["status"], "ok")
        self.assertEqual(archive["integrity"]["replay_consistent"], True)
        self.assertEqual(archive["integrity"]["event_chain_consistent"], True)
        self.assertEqual(archive["integrity"]["document_count"], 1)
        self.assertEqual(archive["integrity"]["document_event_count"], 2)
        self.assertEqual(archive["integrity"]["documents"][0]["replay_matches_latest"], True)
        self.assertEqual(archive["integrity"]["documents"][0]["event_chain_status"], "ok")
        self.assertEqual(archive["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(archive["integrity"]["checks"]["event_chain"]["status"], "ok")
        self.assertEqual(archive["integrity"]["checks"]["event_chain"]["failure_count"], 0)
        self.assertEqual(archive["comments"], [])
        self.assertEqual(archive["reviews"], [])
        self.assertEqual(archive["audit_log"], [])
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._audit_count(), before_audit)

    def test_export_integrity_reports_event_chain_metadata_failure_without_mutation(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/event-chain-export.json",
            content={"value": 1},
        )
        self._insert_event(
            document_id=document["id"],
            event_id="evt_bad_export_metadata",
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
        before_events = self._event_count()
        before_audit = self._audit_count()

        archive = export_project_archive(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(archive["integrity"]["status"], "failed")
        self.assertEqual(archive["integrity"]["replay_consistent"], True)
        self.assertEqual(archive["integrity"]["event_chain_consistent"], False)
        self.assertEqual(archive["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(archive["integrity"]["checks"]["event_chain"]["status"], "failed")
        self.assertEqual(archive["integrity"]["checks"]["event_chain"]["failure_count"], 1)
        self.assertEqual(archive["integrity"]["documents"][0]["event_chain_status"], "failed")
        failure_codes = {
            failure["error_code"]
            for failure in archive["integrity"]["checks"]["event_chain"]["failures"][0]["failures"]
        }
        self.assertIn("EVENT_BEFORE_VALUES_MISMATCH", failure_codes)
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._audit_count(), before_audit)

    def test_export_reports_malformed_snapshot_json_without_crashing(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/malformed-snapshot-export.json",
            content={"value": 1},
        )
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_snapshot_json = ?
                WHERE id = ?
                """,
                ('{"value":', document["id"]),
            )

        archive = export_project_archive(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )

        self.assertEqual(archive["integrity"]["status"], "failed")
        self.assertEqual(archive["integrity"]["replay_consistent"], False)
        self.assertEqual(archive["integrity"]["event_chain_consistent"], False)
        exported_document = archive["documents"][0]
        self.assertEqual(exported_document["id"], document["id"])
        self.assertIsNone(exported_document["content"])
        self.assertEqual(exported_document["content_error"]["field"], "current_snapshot_json")
        self.assertEqual(archive["integrity"]["checks"]["replay"]["status"], "failed")
        self.assertEqual(archive["integrity"]["checks"]["replay"]["failures"][0]["error_code"], "SNAPSHOT_JSON_DECODE_FAILED")
        event_chain_failures = archive["integrity"]["checks"]["event_chain"]["failures"][0]["failures"]
        self.assertIn("SNAPSHOT_JSON_DECODE_FAILED", {failure["error_code"] for failure in event_chain_failures})

    def test_http_export_reports_malformed_event_json_without_server_error(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/malformed-event-export.json",
            content={"value": 1},
        )
        self._insert_malformed_patch_event(document_id=document["id"], event_id="evt_export_bad_json")
        client = TestClient(create_app(self.db_path))

        response = client.get(
            f"/projects/{self.project['id']}/export",
            headers={"X-Actor-Id": self.owner["id"]},
        )

        self.assertEqual(response.status_code, 200)
        archive = response.json()
        self.assertEqual(archive["integrity"]["status"], "failed")
        self.assertEqual(archive["integrity"]["replay_consistent"], False)
        self.assertEqual(archive["integrity"]["event_chain_consistent"], False)
        exported_document = archive["documents"][0]
        self.assertEqual(exported_document["id"], document["id"])
        self.assertEqual(exported_document["content"], {"value": 1})
        self.assertEqual(exported_document["events"][1]["id"], "evt_export_bad_json")
        self.assertIsNone(exported_document["events"][1]["patch"])
        self.assertEqual(exported_document["events"][1]["json_errors"][0]["field"], "patch")
        replay_failure = archive["integrity"]["checks"]["replay"]["failures"][0]
        event_failure = archive["integrity"]["checks"]["event_chain"]["failures"][0]["failures"][0]
        self.assertEqual(replay_failure["error_code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(replay_failure["details"]["failures"][0]["details"]["field"], "patch")
        self.assertEqual(event_failure["error_code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(event_failure["event_id"], "evt_export_bad_json")
        self.assertEqual(event_failure["details"]["field"], "patch")

    def test_soft_deleted_documents_are_hidden_by_default_and_optionally_exported(self) -> None:
        active = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/active.json",
            content={"active": True},
        )
        deleted = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/deleted.json",
            content={"deleted": True},
        )
        delete_document(
            self.db_path,
            document_id=deleted["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )

        default_archive = export_project_archive(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        full_archive = export_project_archive(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            include_deleted=True,
        )

        self.assertEqual([document["id"] for document in default_archive["documents"]], [active["id"]])
        exported_by_id = {document["id"]: document for document in full_archive["documents"]}
        self.assertIn(active["id"], exported_by_id)
        self.assertIn(deleted["id"], exported_by_id)
        self.assertIsNotNone(exported_by_id[deleted["id"]]["deleted_at"])
        self.assertEqual([event["event_type"] for event in exported_by_id[deleted["id"]]["events"]], ["create", "delete"])

    def test_optional_comments_reviews_and_audit_log_are_included_only_when_requested(self) -> None:
        _schema, document = self._create_schema_and_document()
        thread = create_comment_thread(
            self.db_path,
            document_id=document["id"],
            actor_id=self.editor["id"],
            body="Check exported comment",
            anchor_type="path",
            path="/value",
        )
        review = create_review_request(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.editor["id"],
            title="Review exported change",
            description="Export should include proposal when requested.",
            changes=[
                {
                    "document_id": document["id"],
                    "base_version": 2,
                    "patch": [{"op": "replace", "path": "/value", "value": 3}],
                    "reason": "Exported proposal",
                }
            ],
        )

        default_archive = export_project_archive(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        expanded_archive = export_project_archive(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            include_comments=True,
            include_reviews=True,
            include_audit_log=True,
        )

        self.assertEqual(default_archive["comments"], [])
        self.assertEqual(default_archive["reviews"], [])
        self.assertEqual(default_archive["audit_log"], [])
        self.assertEqual(expanded_archive["comments"][0]["id"], thread["id"])
        self.assertEqual(expanded_archive["comments"][0]["comments"][0]["body"], "Check exported comment")
        self.assertEqual(expanded_archive["reviews"][0]["id"], review["id"])
        self.assertEqual(expanded_archive["reviews"][0]["changes"][0]["reason"], "Exported proposal")
        self.assertGreaterEqual(len(expanded_archive["audit_log"]), 3)
        self.assertEqual(expanded_archive["options"]["include_comments"], True)
        self.assertEqual(expanded_archive["options"]["include_reviews"], True)
        self.assertEqual(expanded_archive["options"]["include_audit_log"], True)

    def test_export_permission_policy_owner_admin_only(self) -> None:
        self._create_schema_and_document()
        for actor, allowed in (
            (self.owner, True),
            (self.admin, True),
            (self.editor, False),
            (self.viewer, False),
            (self.nonmember, False),
        ):
            if allowed:
                archive = export_project_archive(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=actor["id"],
                )
                self.assertEqual(archive["project"]["id"], self.project["id"])
            else:
                with self.assertRaises(AppError) as denied:
                    export_project_archive(
                        self.db_path,
                        project_id=self.project["id"],
                        actor_id=actor["id"],
                    )
                self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_http_route_and_api_token_scope(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/http.json",
            content={"value": 1},
        )
        create_document(
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
            json={"name": "owner export token"},
        )
        viewer_token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.viewer["id"]},
            json={"name": "viewer export token"},
        )
        self.assertEqual(owner_token_response.status_code, 200)
        self.assertEqual(viewer_token_response.status_code, 200)
        owner_token = owner_token_response.json()["token"]
        viewer_token = viewer_token_response.json()["token"]

        exported = client.get(
            f"/projects/{self.project['id']}/export",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        other_project_export = client.get(
            f"/projects/{self.other_project['id']}/export",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        viewer_export = client.get(
            f"/projects/{self.project['id']}/export",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )

        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json()["documents"][0]["id"], document["id"])
        self.assertEqual(exported.json()["integrity"]["status"], "ok")
        self.assertEqual(exported.json()["integrity"]["replay_consistent"], True)
        self.assertEqual(exported.json()["integrity"]["event_chain_consistent"], True)
        self.assertEqual(exported.json()["integrity"]["checks"]["event_chain"]["status"], "ok")
        self.assertEqual(other_project_export.status_code, 403)
        self.assertEqual(other_project_export.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(viewer_export.status_code, 403)
        self.assertEqual(viewer_export.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

    def test_project_export_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/export", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
