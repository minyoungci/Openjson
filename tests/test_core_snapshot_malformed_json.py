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
    get_document,
    patch_document,
    preview_document_patch,
    restore_document,
    rollback_document,
    search_project_documents,
    validate_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.workspace_service import create_project, create_user, create_workspace


class CoreSnapshotMalformedJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.owner = create_user(self.db_path, email="owner@example.com", display_name="Owner")
        self.workspace = create_workspace(self.db_path, actor_id=self.owner["id"], name="Workspace")
        self.project = create_project(
            self.db_path,
            workspace_id=self.workspace["id"],
            actor_id=self.owner["id"],
            name="Project",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_document(self, full_path: str = "config/malformed-snapshot.json") -> dict:
        return create_document(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            full_path=full_path,
            content={"value": 1},
        )

    def _corrupt_snapshot(self, document_id: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE json_documents
                SET current_snapshot_json = ?
                WHERE id = ?
                """,
                ('{"value":', document_id),
            )

    def _document_row(self, document_id: str) -> dict:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT current_version, current_snapshot_json, deleted_at
                FROM json_documents
                WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
        return {
            "current_version": row["current_version"],
            "current_snapshot_json": row["current_snapshot_json"],
            "deleted_at": row["deleted_at"],
        }

    def _event_count(self, document_id: str) -> int:
        with connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (document_id,),
            ).fetchone()["count"]

    def _assert_snapshot_decode_error(self, error: AppError, document_id: str) -> None:
        self.assertEqual(error.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(error.message, "Document current_snapshot_json is malformed.")
        self.assertEqual(error.details["diagnostic_code"], "SNAPSHOT_JSON_DECODE_FAILED")
        self.assertEqual(error.details["document_id"], document_id)
        self.assertEqual(error.details["project_id"], self.project["id"])
        self.assertEqual(error.details["field"], "current_snapshot_json")
        self.assertEqual(error.details["message"], "Expecting value")

    def test_get_document_returns_structured_malformed_snapshot_error(self) -> None:
        document = self._create_document()
        self._corrupt_snapshot(document["id"])
        client = TestClient(create_app(self.db_path))

        with self.assertRaises(AppError) as raised:
            get_document(self.db_path, document["id"], actor_id=self.owner["id"])
        response = client.get(
            f"/documents/{document['id']}",
            headers={"X-Actor-Id": self.owner["id"]},
        )

        self._assert_snapshot_decode_error(raised.exception, document["id"])
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"]["code"], ErrorCode.INTERNAL_ERROR)
        self.assertEqual(body["error"]["details"]["diagnostic_code"], "SNAPSHOT_JSON_DECODE_FAILED")
        self.assertEqual(body["error"]["details"]["document_id"], document["id"])

    def test_document_search_reports_partial_malformed_snapshot_diagnostics(self) -> None:
        document = self._create_document("config/search-malformed.json")
        self._corrupt_snapshot(document["id"])
        before_event_count = self._event_count(document["id"])
        client = TestClient(create_app(self.db_path))

        result = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="search",
        )
        content_only = search_project_documents(
            self.db_path,
            project_id=self.project["id"],
            actor_id=self.owner["id"],
            q="value",
        )
        response = client.get(
            f"/projects/{self.project['id']}/document-search",
            headers={"X-Actor-Id": self.owner["id"]},
            params={"q": "search"},
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["snapshot_errors"][0]["diagnostic_code"], "SNAPSHOT_JSON_DECODE_FAILED")
        self.assertEqual(result["snapshot_errors"][0]["document_id"], document["id"])
        self.assertEqual(result["documents"][0]["id"], document["id"])
        self.assertEqual(result["documents"][0]["matches"][0]["match_type"], "full_path")
        self.assertEqual(result["documents"][0]["snapshot_error"]["diagnostic_code"], "SNAPSHOT_JSON_DECODE_FAILED")
        self.assertEqual(content_only["status"], "partial")
        self.assertEqual(content_only["documents"], [])
        self.assertEqual(content_only["snapshot_errors"][0]["document_id"], document["id"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "partial")
        self.assertEqual(response.json()["snapshot_errors"][0]["document_id"], document["id"])
        self.assertEqual(response.json()["documents"][0]["snapshot_error"]["field"], "current_snapshot_json")
        self.assertEqual(self._event_count(document["id"]), before_event_count)

    def test_patch_delete_preview_restore_validate_and_rollback_reject_malformed_snapshot_safely(self) -> None:
        for operation in ("patch", "delete", "preview", "restore", "validate", "rollback"):
            with self.subTest(operation=operation):
                document = self._create_document(f"config/{operation}-malformed.json")
                if operation == "restore":
                    delete_document(
                        self.db_path,
                        document_id=document["id"],
                        actor_id=self.owner["id"],
                        base_version=1,
                    )
                elif operation == "rollback":
                    patch_document(
                        self.db_path,
                        document_id=document["id"],
                        actor_id=self.owner["id"],
                        base_version=1,
                        patch=[{"op": "replace", "path": "/value", "value": 2}],
                    )
                self._corrupt_snapshot(document["id"])
                before_row = self._document_row(document["id"])
                before_event_count = self._event_count(document["id"])

                with self.assertRaises(AppError) as raised:
                    if operation == "patch":
                        patch_document(
                            self.db_path,
                            document_id=document["id"],
                            actor_id=self.owner["id"],
                            base_version=1,
                            patch=[{"op": "replace", "path": "/value", "value": 2}],
                        )
                    elif operation == "preview":
                        preview_document_patch(
                            self.db_path,
                            document_id=document["id"],
                            actor_id=self.owner["id"],
                            base_version=1,
                            patch=[{"op": "replace", "path": "/value", "value": 2}],
                        )
                    elif operation == "delete":
                        delete_document(
                            self.db_path,
                            document_id=document["id"],
                            actor_id=self.owner["id"],
                            base_version=1,
                        )
                    elif operation == "restore":
                        restore_document(
                            self.db_path,
                            document_id=document["id"],
                            actor_id=self.owner["id"],
                            base_version=2,
                        )
                    elif operation == "validate":
                        validate_document(
                            self.db_path,
                            document_id=document["id"],
                            actor_id=self.owner["id"],
                        )
                    elif operation == "rollback":
                        rollback_document(
                            self.db_path,
                            document_id=document["id"],
                            actor_id=self.owner["id"],
                            base_version=2,
                            target_version=1,
                        )
                    else:
                        raise AssertionError(f"Unhandled operation: {operation}")

                self._assert_snapshot_decode_error(raised.exception, document["id"])
                self.assertEqual(self._event_count(document["id"]), before_event_count)
                self.assertEqual(self._document_row(document["id"]), before_row)


if __name__ == "__main__":
    unittest.main()
