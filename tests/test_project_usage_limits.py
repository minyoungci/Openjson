from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import connect, init_db, utc_now
from app.document_service import (
    create_document,
    get_document,
    get_history,
    patch_document,
    rollback_document,
)
from app.errors import AppError, ErrorCode
from app.main import create_app
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


class ProjectUsageLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._clear_usage_limit_env()
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
        self._clear_usage_limit_env()

    def _clear_usage_limit_env(self) -> None:
        import os

        os.environ.pop("OPENJSON_PROJECT_USAGE_LIMIT_ENABLED", None)
        os.environ.pop("OPENJSON_MAX_PROJECT_DOCUMENTS", None)
        os.environ.pop("OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES", None)

    def _counts(self) -> tuple[int, int]:
        with connect(self.db_path) as conn:
            document_count = conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"]
            event_count = conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"]
        return document_count, event_count

    def test_project_usage_endpoint_reports_active_snapshot_usage_and_limits(self) -> None:
        create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="config/app.json",
            content={"name": "app"},
        )
        create_document(
            self.db_path,
            project_id=self.project_id,
            actor_id=self.actor_id,
            full_path="data/items.json",
            content=[{"id": "one"}],
        )
        client = TestClient(create_app(self.db_path))

        response = client.get(f"/projects/{self.project_id}/usage", headers={"X-Actor-Id": self.actor_id})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["project_id"], self.project_id)
        self.assertEqual(body["usage"]["active_document_count"], 2)
        self.assertGreater(body["usage"]["active_snapshot_bytes"], 0)
        self.assertFalse(body["limits"]["enabled"])
        self.assertEqual(body["limits"]["max_project_documents"], 10000)

    def test_document_count_limit_rejects_create_without_event(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENJSON_PROJECT_USAGE_LIMIT_ENABLED": "1",
                "OPENJSON_MAX_PROJECT_DOCUMENTS": "1",
                "OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES": "1000000",
            },
            clear=False,
        ):
            create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                full_path="one.json",
                content={"one": True},
            )
            with self.assertRaises(AppError) as raised:
                create_document(
                    self.db_path,
                    project_id=self.project_id,
                    actor_id=self.actor_id,
                    full_path="two.json",
                    content={"two": True},
                )

        self.assertEqual(raised.exception.code, ErrorCode.PROJECT_USAGE_LIMIT_EXCEEDED)
        self.assertEqual(self._counts(), (1, 1))

    def test_snapshot_byte_limit_rejects_patch_without_event_or_snapshot_change(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENJSON_PROJECT_USAGE_LIMIT_ENABLED": "1",
                "OPENJSON_MAX_PROJECT_DOCUMENTS": "10",
                "OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES": "80",
            },
            clear=False,
        ):
            document = create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                full_path="config/app.json",
                content={"name": "ok"},
            )
            with self.assertRaises(AppError) as raised:
                patch_document(
                    self.db_path,
                    document_id=document["id"],
                    actor_id=self.actor_id,
                    base_version=1,
                    patch=[{"op": "replace", "path": "/name", "value": "x" * 200}],
                )

        self.assertEqual(raised.exception.code, ErrorCode.PROJECT_USAGE_LIMIT_EXCEEDED)
        current = get_document(self.db_path, document["id"], actor_id=self.actor_id)
        self.assertEqual(current["current_version"], 1)
        self.assertEqual(current["content"], {"name": "ok"})
        self.assertEqual(len(get_history(self.db_path, document["id"], actor_id=self.actor_id)["events"]), 1)

    def test_rollback_to_larger_snapshot_respects_usage_limit_without_event(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENJSON_PROJECT_USAGE_LIMIT_ENABLED": "1",
                "OPENJSON_MAX_PROJECT_DOCUMENTS": "10",
                "OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES": "1000",
            },
            clear=False,
        ):
            document = create_document(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                full_path="config/app.json",
                content={"name": "x" * 200},
            )
            patch_document(
                self.db_path,
                document_id=document["id"],
                actor_id=self.actor_id,
                base_version=1,
                patch=[{"op": "replace", "path": "/name", "value": "ok"}],
            )

        with patch.dict(
            "os.environ",
            {
                "OPENJSON_PROJECT_USAGE_LIMIT_ENABLED": "1",
                "OPENJSON_MAX_PROJECT_DOCUMENTS": "10",
                "OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES": "80",
            },
            clear=False,
        ):
            with self.assertRaises(AppError) as raised:
                rollback_document(
                    self.db_path,
                    document_id=document["id"],
                    actor_id=self.actor_id,
                    base_version=2,
                    target_version=1,
                )

        self.assertEqual(raised.exception.code, ErrorCode.PROJECT_USAGE_LIMIT_EXCEEDED)
        current = get_document(self.db_path, document["id"], actor_id=self.actor_id)
        self.assertEqual(current["current_version"], 2)
        self.assertEqual(current["content"], {"name": "ok"})
        self.assertEqual(len(get_history(self.db_path, document["id"], actor_id=self.actor_id)["events"]), 2)

    def test_zip_preview_and_apply_are_blocked_by_project_usage_limit_without_partial_writes(self) -> None:
        archive = make_zip(
            [
                ("one.json", {"one": True}),
                ("two.json", {"two": True}),
            ]
        )
        with patch.dict(
            "os.environ",
            {
                "OPENJSON_PROJECT_USAGE_LIMIT_ENABLED": "1",
                "OPENJSON_MAX_PROJECT_DOCUMENTS": "1",
                "OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES": "1000000",
            },
            clear=False,
        ):
            preview = preview_zip_import(
                self.db_path,
                project_id=self.project_id,
                actor_id=self.actor_id,
                archive_bytes=archive,
            )
            with self.assertRaises(AppError) as raised:
                apply_zip_import(
                    self.db_path,
                    project_id=self.project_id,
                    actor_id=self.actor_id,
                    archive_bytes=archive,
                )

        self.assertFalse(preview["can_apply"])
        self.assertEqual(preview["errors"][0]["code"], ErrorCode.PROJECT_USAGE_LIMIT_EXCEEDED)
        self.assertEqual(raised.exception.code, ErrorCode.ZIP_IMPORT_PRECHECK_FAILED)
        self.assertEqual(self._counts(), (0, 0))


if __name__ == "__main__":
    unittest.main()
