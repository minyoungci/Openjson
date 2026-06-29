from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.document_service import create_document, delete_document
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.schema_service import create_schema
from app.validation_report_service import get_project_validation_report
from app.workspace_service import add_project_member, create_project, create_user, create_workspace


class ProjectValidationReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.admin = create_user(self.db_path, email="admin@example.com", display_name="Admin")
        self.editor = create_user(self.db_path, email="editor@example.com", display_name="Editor")
        self.reviewer = create_user(self.db_path, email="reviewer@example.com", display_name="Reviewer")
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
        for user, role in (
            (self.admin, "admin"),
            (self.editor, "editor"),
            (self.reviewer, "reviewer"),
            (self.viewer, "viewer"),
        ):
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
                    f"Tampered validation report event {event_id}",
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
                    f"Malformed validation report event {event_id}",
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

    def _create_number_schema(self) -> dict:
        return create_schema(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name="number-value",
            version="1",
            schema_json={
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "number", "minimum": 10}},
                "additionalProperties": True,
            },
        )

    def _bind_schema_directly(self, document_id: str, schema_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET schema_id = ?
                WHERE id = ?
                """,
                (schema_id, document_id),
            )

    def _create_schema_valid_event_metadata_failure(self) -> dict:
        schema = self._create_number_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/event-chain-validation.json",
            schema_id=schema["id"],
            content={"value": 20},
        )
        self._insert_event(
            document_id=document["id"],
            event_id="evt_bad_validation_metadata",
            event_type="update",
            base_version=1,
            result_version=2,
            patch=[{"op": "replace", "path": "/value", "value": 30}],
            inverse_patch=[{"op": "replace", "path": "/value", "value": 20}],
            changed_paths=["/value"],
            before_values=[{"path": "/value", "exists": True, "value": 999}],
            after_values=[{"path": "/value", "exists": True, "value": 30}],
        )
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_version = 2,
                    current_snapshot_json = ?
                WHERE id = ?
                """,
                (json.dumps({"value": 30}, separators=(",", ":")), document["id"]),
            )
        return document

    def test_report_summarizes_bound_valid_invalid_and_unbound_documents_without_mutation(self) -> None:
        schema = self._create_number_schema()
        valid_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/valid.json",
            schema_id=schema["id"],
            content={"value": 20},
        )
        invalid_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/invalid.json",
            content={"value": 1},
        )
        self._bind_schema_directly(invalid_doc["id"], schema["id"])
        unbound_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/unbound.json",
            content={"free": True},
        )
        before_events = self._event_count()
        before_audit = self._audit_count()

        report = get_project_validation_report(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.editor["id"],
        )

        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["integrity"]["status"], "ok")
        self.assertEqual(report["integrity"]["replay_consistent"], True)
        self.assertEqual(report["integrity"]["event_chain_consistent"], True)
        self.assertEqual(report["integrity"]["checks"]["replay"]["checked_documents"], 3)
        self.assertEqual(report["integrity"]["checks"]["event_chain"]["checked_documents"], 3)
        self.assertEqual(report["summary"], {
            "checked_documents": 3,
            "valid_documents": 2,
            "invalid_documents": 1,
            "unbound_documents": 1,
            "deleted_documents": 0,
        })
        by_id = {document["document_id"]: document for document in report["documents"]}
        self.assertTrue(by_id[valid_doc["id"]]["validation"]["valid"])
        self.assertFalse(by_id[invalid_doc["id"]]["validation"]["valid"])
        self.assertEqual(by_id[invalid_doc["id"]]["validation"]["errors"][0]["path"], "/value")
        self.assertEqual(by_id[invalid_doc["id"]]["validation"]["errors"][0]["validator"], "minimum")
        self.assertTrue(by_id[unbound_doc["id"]]["validation"]["valid"])
        self.assertEqual(by_id[unbound_doc["id"]]["validation"]["warnings"][0]["message"], "Document has no schema binding.")
        self.assertEqual(by_id[valid_doc["id"]]["integrity"]["event_chain_status"], "ok")
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._audit_count(), before_audit)

    def test_report_integrity_detects_event_metadata_failure_even_when_schema_valid(self) -> None:
        document = self._create_schema_valid_event_metadata_failure()
        before_events = self._event_count()
        before_audit = self._audit_count()

        report = get_project_validation_report(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.editor["id"],
        )

        self.assertEqual(report["status"], "valid")
        self.assertEqual(report["integrity"]["status"], "failed")
        self.assertEqual(report["integrity"]["replay_consistent"], True)
        self.assertEqual(report["integrity"]["event_chain_consistent"], False)
        self.assertEqual(report["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(report["integrity"]["checks"]["event_chain"]["status"], "failed")
        self.assertEqual(report["integrity"]["checks"]["event_chain"]["failure_count"], 1)
        self.assertEqual(report["documents"][0]["document_id"], document["id"])
        self.assertTrue(report["documents"][0]["validation"]["valid"])
        self.assertEqual(report["documents"][0]["integrity"]["event_chain_status"], "failed")
        failure_codes = {
            failure["error_code"]
            for failure in report["integrity"]["checks"]["event_chain"]["failures"][0]["failures"]
        }
        self.assertIn("EVENT_BEFORE_VALUES_MISMATCH", failure_codes)
        self.assertEqual(self._event_count(), before_events)
        self.assertEqual(self._audit_count(), before_audit)

    def test_report_returns_structured_failure_for_malformed_snapshot_json(self) -> None:
        schema = self._create_number_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/malformed-snapshot.json",
            schema_id=schema["id"],
            content={"value": 20},
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

        report = get_project_validation_report(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.editor["id"],
        )

        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["summary"]["invalid_documents"], 1)
        self.assertEqual(report["integrity"]["status"], "failed")
        document_report = report["documents"][0]
        self.assertEqual(document_report["document_id"], document["id"])
        self.assertFalse(document_report["validation"]["valid"])
        self.assertEqual(document_report["validation"]["errors"][0]["validator"], "json_syntax")
        self.assertEqual(document_report["validation"]["errors"][0]["details"]["field"], "current_snapshot_json")
        self.assertEqual(document_report["integrity"]["replay_status"], "failed")
        self.assertEqual(document_report["integrity"]["event_chain_status"], "failed")
        self.assertEqual(
            report["integrity"]["checks"]["replay"]["failures"][0]["error_code"],
            "SNAPSHOT_JSON_DECODE_FAILED",
        )
        event_chain_failures = report["integrity"]["checks"]["event_chain"]["failures"][0]["failures"]
        self.assertIn("SNAPSHOT_JSON_DECODE_FAILED", {failure["error_code"] for failure in event_chain_failures})

    def test_http_report_returns_structured_failure_for_malformed_event_json(self) -> None:
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/malformed-event.json",
            content={"value": 20},
        )
        self._insert_malformed_patch_event(document_id=document["id"], event_id="evt_validation_bad_json")
        client = TestClient(create_app(self.db_path))

        response = client.get(
            f"/projects/{self.project['id']}/validation-report",
            headers={"X-Actor-Id": self.editor["id"]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "valid")
        self.assertEqual(payload["integrity"]["status"], "failed")
        self.assertEqual(payload["integrity"]["checks"]["replay"]["status"], "failed")
        self.assertEqual(payload["integrity"]["checks"]["event_chain"]["status"], "failed")
        replay_failure = payload["integrity"]["checks"]["replay"]["failures"][0]
        event_failure = payload["integrity"]["checks"]["event_chain"]["failures"][0]["failures"][0]
        self.assertEqual(replay_failure["error_code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(replay_failure["details"]["failures"][0]["details"]["field"], "patch")
        self.assertEqual(event_failure["error_code"], "EVENT_JSON_DECODE_FAILED")
        self.assertEqual(event_failure["event_id"], "evt_validation_bad_json")
        self.assertEqual(event_failure["details"]["field"], "patch")

    def test_only_invalid_preserves_summary_and_filters_returned_documents(self) -> None:
        schema = self._create_number_schema()
        create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/valid.json",
            schema_id=schema["id"],
            content={"value": 20},
        )
        invalid_doc = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/invalid.json",
            content={"value": 1},
        )
        self._bind_schema_directly(invalid_doc["id"], schema["id"])

        report = get_project_validation_report(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.reviewer["id"],
            only_invalid=True,
        )

        self.assertEqual(report["summary"]["checked_documents"], 2)
        self.assertEqual(report["summary"]["invalid_documents"], 1)
        self.assertEqual([document["document_id"] for document in report["documents"]], [invalid_doc["id"]])
        self.assertTrue(report["only_invalid"])

    def test_only_invalid_does_not_hide_integrity_failures(self) -> None:
        self._create_schema_valid_event_metadata_failure()

        report = get_project_validation_report(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            only_invalid=True,
        )

        self.assertEqual(report["status"], "valid")
        self.assertEqual(report["documents"], [])
        self.assertEqual(report["summary"]["checked_documents"], 1)
        self.assertEqual(report["summary"]["invalid_documents"], 0)
        self.assertEqual(report["integrity"]["status"], "failed")
        self.assertEqual(report["integrity"]["checks"]["event_chain"]["failure_count"], 1)

    def test_include_deleted_policy(self) -> None:
        schema = self._create_number_schema()
        active = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/active.json",
            schema_id=schema["id"],
            content={"value": 20},
        )
        deleted = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/deleted.json",
            schema_id=schema["id"],
            content={"value": 30},
        )
        delete_document(
            self.db_path,
            document_id=deleted["id"],
            actor_id=self.owner["id"],
            base_version=1,
        )

        default_report = get_project_validation_report(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )
        with_deleted = get_project_validation_report(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            include_deleted=True,
        )

        self.assertEqual([document["document_id"] for document in default_report["documents"]], [active["id"]])
        self.assertEqual({document["document_id"] for document in with_deleted["documents"]}, {active["id"], deleted["id"]})
        self.assertEqual(with_deleted["summary"]["deleted_documents"], 1)

    def test_json_pointer_error_paths_preserve_escaping(self) -> None:
        schema = create_schema(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            name="escaped",
            version="1",
            schema_json={
                "type": "object",
                "properties": {
                    "a/b": {"type": "number", "minimum": 10},
                    "c~d": {"type": "number", "maximum": 5},
                },
            },
        )
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/escaped.json",
            content={"a/b": 1, "c~d": 9},
        )
        self._bind_schema_directly(document["id"], schema["id"])

        report = get_project_validation_report(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
        )

        errors = {error["path"]: error for error in report["documents"][0]["validation"]["errors"]}
        self.assertIn("/a~1b", errors)
        self.assertIn("/c~0d", errors)

    def test_validation_report_permission_policy(self) -> None:
        create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/doc.json",
            content={"value": 1},
        )
        for actor, allowed in (
            (self.owner, True),
            (self.admin, True),
            (self.editor, True),
            (self.reviewer, True),
            (self.viewer, False),
            (self.nonmember, False),
        ):
            if allowed:
                report = get_project_validation_report(
                    self.db_path,
                    project_id=self.project["id"],
                    actor_id=actor["id"],
                )
                self.assertEqual(report["project_id"], self.project["id"])
            else:
                with self.assertRaises(AppError) as denied:
                    get_project_validation_report(
                        self.db_path,
                        project_id=self.project["id"],
                        actor_id=actor["id"],
                    )
                self.assertEqual(denied.exception.code, ErrorCode.PERMISSION_DENIED)

    def test_http_route_and_api_token_scope(self) -> None:
        schema = self._create_number_schema()
        document = create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path="config/http.json",
            schema_id=schema["id"],
            content={"value": 20},
        )
        create_document(
            self.db_path,
            project_id=self.other_project["id"],
            actor_id=self.owner["id"],
            full_path="config/other.json",
            content={"other": True},
        )
        client = TestClient(create_app(self.db_path))
        editor_token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.editor["id"]},
            json={"name": "editor validation token"},
        )
        viewer_token_response = client.post(
            f"/projects/{self.project['id']}/api-tokens",
            headers={"X-Actor-Id": self.viewer["id"]},
            json={"name": "viewer validation token"},
        )
        self.assertEqual(editor_token_response.status_code, 200)
        self.assertEqual(viewer_token_response.status_code, 200)
        editor_token = editor_token_response.json()["token"]
        viewer_token = viewer_token_response.json()["token"]

        report_response = client.get(
            f"/projects/{self.project['id']}/validation-report",
            headers={"Authorization": f"Bearer {editor_token}"},
        )
        other_project_response = client.get(
            f"/projects/{self.other_project['id']}/validation-report",
            headers={"Authorization": f"Bearer {editor_token}"},
        )
        viewer_response = client.get(
            f"/projects/{self.project['id']}/validation-report",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )

        self.assertEqual(report_response.status_code, 200)
        self.assertEqual(report_response.json()["documents"][0]["document_id"], document["id"])
        self.assertEqual(report_response.json()["integrity"]["status"], "ok")
        self.assertEqual(report_response.json()["integrity"]["checks"]["replay"]["status"], "ok")
        self.assertEqual(report_response.json()["integrity"]["checks"]["event_chain"]["status"], "ok")
        self.assertEqual(other_project_response.status_code, 403)
        self.assertEqual(other_project_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)
        self.assertEqual(viewer_response.status_code, 403)
        self.assertEqual(viewer_response.json()["error"]["code"], ErrorCode.PERMISSION_DENIED)

    def test_project_validation_report_route_is_registered(self) -> None:
        app = create_app(self.db_path)
        routes = {(route.path, ",".join(sorted(route.methods))) for route in app.routes if hasattr(route, "methods")}

        self.assertIn(("/projects/{project_id}/validation-report", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
