from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db, utc_now
from app.document_service import assert_replay_matches_latest, create_document, get_history
from app.errors import AppError, ErrorCode
from app.main import create_app
from app.schema_service import create_schema
from app.zip_import_service import apply_zip_import, preview_zip_import


def make_zip(entries: list[tuple[str, object | str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, value in entries:
            if isinstance(value, str):
                archive.writestr(path, value)
            else:
                archive.writestr(path, json.dumps(value, ensure_ascii=False))
    return buffer.getvalue()


class ZipImportTests(unittest.TestCase):
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

    def _counts(self) -> tuple[int, int]:
        with connect(self.db_path) as conn:
            document_count = conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"]
            event_count = conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]
        return document_count, event_count

    def _create_config_schema(self) -> dict:
        return create_schema(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            name="config",
            version="1",
            schema_json={
                "type": "object",
                "required": ["kind"],
                "properties": {"kind": {"const": "config"}},
                "additionalProperties": True,
            },
            file_pattern="config/*.json",
        )

    def test_preview_reports_folders_schema_matches_and_references(self) -> None:
        schema = self._create_config_schema()
        archive = make_zip(
            [
                (
                    "config/app.json",
                    {
                        "kind": "config",
                        "model": "../models/base.json",
                        "$ref": "../schemas/defs.json#/$defs/app",
                    },
                ),
                ("models/base.json", [{"name": "base"}]),
                ("README.md", "not imported"),
            ]
        )

        preview = preview_zip_import(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            archive_bytes=archive,
        )

        self.assertTrue(preview["can_apply"])
        self.assertEqual(preview["archive"]["json_file_count"], 2)
        self.assertEqual(preview["archive"]["skipped_file_count"], 1)
        self.assertEqual(
            preview["folders"],
            [{"path": "config", "json_file_count": 1}, {"path": "models", "json_file_count": 1}],
        )
        config_file = next(item for item in preview["files"] if item["path"] == "config/app.json")
        self.assertEqual(config_file["schema_match"]["status"], "matched")
        self.assertEqual(config_file["schema_id"], schema["id"])
        self.assertEqual(config_file["validation"]["valid"], True)
        statuses = {
            (edge["target_path"], edge["target_status"])
            for edge in preview["references"]["edges"]
        }
        self.assertIn(("models/base.json", "in_archive"), statuses)
        self.assertIn(("schemas/defs.json", "missing"), statuses)
        self.assertEqual(self._counts(), (0, 0))

    def test_apply_creates_documents_events_and_replay_matches(self) -> None:
        archive = make_zip(
            [
                ("config/app.json", {"name": "app", "model": "../models/base.json"}),
                ("models/base.json", {"name": "base"}),
            ]
        )

        applied = apply_zip_import(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            archive_bytes=archive,
            reason="Initial team JSON import",
        )

        self.assertTrue(applied["applied"])
        self.assertEqual(applied["imported_count"], 2)
        self.assertEqual(self._counts(), (2, 2))
        for document in applied["created_documents"]:
            self.assertEqual(document["current_version"], 1)
            self.assertEqual(document["event_type"], "create")
            assert_replay_matches_latest(self.db_path, document["id"])
            history = get_history(self.db_path, document["id"], actor_id=self.actor_id)
            self.assertEqual(history["events"][0]["reason"], "Initial team JSON import")

    def test_apply_invalid_json_writes_nothing(self) -> None:
        archive = make_zip(
            [
                ("config/good.json", {"ok": True}),
                ("config/bad.json", '{"broken": }'),
            ]
        )

        with self.assertRaises(AppError) as raised:
            apply_zip_import(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                archive_bytes=archive,
            )

        self.assertEqual(raised.exception.code, ErrorCode.ZIP_IMPORT_PRECHECK_FAILED)
        self.assertEqual(self._counts(), (0, 0))

    def test_active_document_path_conflict_blocks_without_partial_writes(self) -> None:
        create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/existing.json",
            content={"existing": True},
        )
        archive = make_zip(
            [
                ("config/existing.json", {"existing": False}),
                ("config/new.json", {"new": True}),
            ]
        )

        preview = preview_zip_import(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            archive_bytes=archive,
        )

        self.assertFalse(preview["can_apply"])
        conflict_file = next(item for item in preview["files"] if item["path"] == "config/existing.json")
        self.assertEqual(conflict_file["errors"][0]["code"], "DOCUMENT_PATH_CONFLICT")
        with self.assertRaises(AppError) as raised:
            apply_zip_import(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                archive_bytes=archive,
            )
        self.assertEqual(raised.exception.code, ErrorCode.ZIP_IMPORT_PRECHECK_FAILED)
        self.assertEqual(self._counts(), (1, 1))

    def test_schema_validation_failure_blocks_archive(self) -> None:
        self._create_config_schema()
        archive = make_zip(
            [
                ("config/bad.json", {"kind": "wrong"}),
                ("models/base.json", {"name": "base"}),
            ]
        )

        preview = preview_zip_import(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            archive_bytes=archive,
        )

        self.assertFalse(preview["can_apply"])
        bad_file = next(item for item in preview["files"] if item["path"] == "config/bad.json")
        self.assertEqual(bad_file["errors"][0]["code"], ErrorCode.SCHEMA_VALIDATION_FAILED)
        with self.assertRaises(AppError) as raised:
            apply_zip_import(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                archive_bytes=archive,
            )
        self.assertEqual(raised.exception.code, ErrorCode.ZIP_IMPORT_PRECHECK_FAILED)
        self.assertEqual(self._counts(), (0, 0))

    def test_zip_slip_path_is_rejected(self) -> None:
        archive = make_zip([("../bad.json", {"bad": True})])

        with self.assertRaises(AppError) as raised:
            preview_zip_import(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                archive_bytes=archive,
            )

        self.assertEqual(raised.exception.code, ErrorCode.ZIP_IMPORT_INVALID)
        self.assertEqual(self._counts(), (0, 0))

    def test_http_preview_and_apply_accept_raw_zip_body(self) -> None:
        client = TestClient(create_app(self.db_path))
        archive = make_zip([("data/sample.json", {"value": 1})])

        preview_response = client.post(
            f"/projects/{self.project_id}/imports/zip-preview",
            headers={"X-Actor-Id": self.actor_id, "Content-Type": "application/zip"},
            content=archive,
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertTrue(preview_response.json()["can_apply"])

        apply_response = client.post(
            f"/projects/{self.project_id}/imports/zip-apply?reason=HTTP%20import",
            headers={"X-Actor-Id": self.actor_id, "Content-Type": "application/zip"},
            content=archive,
        )
        self.assertEqual(apply_response.status_code, 200)
        body = apply_response.json()
        self.assertEqual(body["imported_count"], 1)
        self.assertEqual(self._counts(), (1, 1))
        assert_replay_matches_latest(self.db_path, body["created_documents"][0]["id"])

