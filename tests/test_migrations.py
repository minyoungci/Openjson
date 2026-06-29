from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.database import KNOWN_SCHEMA_MIGRATIONS, connect, get_schema_migration_status, init_db, utc_now
from app.document_service import assert_replay_matches_latest


class MigrationBaselineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_init_db_records_known_migrations_idempotently(self) -> None:
        init_db(self.db_path)
        init_db(self.db_path)

        status = get_schema_migration_status(self.db_path)

        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["current_schema_version"], KNOWN_SCHEMA_MIGRATIONS[-1][0])
        self.assertEqual(status["expected_migrations"], [migration_id for migration_id, _ in KNOWN_SCHEMA_MIGRATIONS])
        self.assertEqual(status["applied_count"], len(KNOWN_SCHEMA_MIGRATIONS))
        self.assertEqual(status["pending_migrations"], [])
        self.assertEqual(status["unknown_migrations"], [])

    def test_schema_migrations_table_is_append_only(self) -> None:
        init_db(self.db_path)
        migration_id = KNOWN_SCHEMA_MIGRATIONS[0][0]

        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE schema_migrations SET description = ? WHERE id = ?",
                    ("changed", migration_id),
                )
        with connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM schema_migrations WHERE id = ?", (migration_id,))

        self.assertEqual(get_schema_migration_status(self.db_path)["status"], "ok")

    def test_migration_status_detects_unknown_rows(self) -> None:
        init_db(self.db_path)
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO schema_migrations (id, description, applied_at)
                VALUES (?, ?, ?)
                """,
                ("9999_unknown", "Unknown test migration", utc_now()),
            )

        status = get_schema_migration_status(self.db_path)

        self.assertEqual(status["status"], "drift")
        self.assertEqual(status["unknown_migrations"], ["9999_unknown"])

    def test_migrate_db_script_is_idempotent_and_status_reports_ok(self) -> None:
        root = Path(__file__).resolve().parents[1]
        first = subprocess.run(
            [sys.executable, "scripts/migrate_db.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        second = subprocess.run(
            [sys.executable, "scripts/migrate_db.py", "--db-path", self.db_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        checked = subprocess.run(
            [sys.executable, "scripts/migrate_db.py", "--db-path", self.db_path, "--status"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )

        first_payload = json.loads(first.stdout)
        second_payload = json.loads(second.stdout)
        checked_payload = json.loads(checked.stdout)
        self.assertEqual(first_payload["status"], "migrated")
        self.assertEqual(second_payload["migrations"]["applied_count"], len(KNOWN_SCHEMA_MIGRATIONS))
        self.assertEqual(checked_payload["status"], "checked")
        self.assertEqual(checked_payload["migrations"]["status"], "ok")

    def test_legacy_database_upgrade_records_migrations_and_preserves_replay(self) -> None:
        now = utc_now()
        snapshot = {"model": "baseline", "learning_rate": 0.1}
        with connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE projects (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE json_documents (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    full_path TEXT NOT NULL,
                    current_version INTEGER NOT NULL,
                    current_snapshot_json TEXT NOT NULL,
                    created_by TEXT NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE TABLE document_events (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES json_documents(id),
                    actor_id TEXT NOT NULL REFERENCES users(id),
                    event_type TEXT NOT NULL,
                    base_version INTEGER NOT NULL,
                    result_version INTEGER NOT NULL,
                    patch TEXT NOT NULL,
                    inverse_patch TEXT NOT NULL,
                    changed_paths TEXT NOT NULL,
                    before_values TEXT NOT NULL,
                    after_values TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(document_id, result_version)
                );
                """
            )
            conn.execute(
                "INSERT INTO users (id, email, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("user_old", "old@example.com", "Old User", now, now),
            )
            conn.execute(
                "INSERT INTO workspaces (id, name, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("workspace_old", "Old Workspace", "user_old", now, now),
            )
            conn.execute(
                "INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("project_old", "workspace_old", "Old Project", None, now, now),
            )
            conn.execute(
                """
                INSERT INTO json_documents (
                    id, project_id, full_path, current_version, current_snapshot_json,
                    created_by, created_at, updated_at, deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                ("doc_old", "project_old", "config/model.json", 1, json.dumps(snapshot), "user_old", now, now),
            )
            conn.execute(
                """
                INSERT INTO document_events (
                    id, document_id, actor_id, event_type, base_version, result_version,
                    patch, inverse_patch, changed_paths, before_values, after_values,
                    summary, reason, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "evt_old",
                    "doc_old",
                    "user_old",
                    "create",
                    0,
                    1,
                    json.dumps([{"op": "add", "path": "", "value": snapshot}]),
                    json.dumps([{"op": "remove", "path": ""}]),
                    json.dumps([""]),
                    json.dumps([{"path": "", "exists": False, "value": None}]),
                    json.dumps([{"path": "", "exists": True, "value": snapshot}]),
                    "Created config/model.json",
                    None,
                    now,
                ),
            )

        init_db(self.db_path)
        status = get_schema_migration_status(self.db_path)

        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["applied_count"], len(KNOWN_SCHEMA_MIGRATIONS))
        with connect(self.db_path) as conn:
            self.assertIsNotNone(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
                ).fetchone()
            )
            owner_member = conn.execute(
                """
                SELECT role
                FROM project_members
                WHERE project_id = ? AND user_id = ?
                """,
                ("project_old", "user_old"),
            ).fetchone()
        self.assertEqual(owner_member["role"], "owner")
        assert_replay_matches_latest(self.db_path, "doc_old")


if __name__ == "__main__":
    unittest.main()
