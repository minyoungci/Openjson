from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.main import create_app
from scripts.smoke_team_workspace_flow import run_team_workspace_smoke


class TeamWorkspaceSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)
        self.client = TestClient(create_app(self.db_path))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_team_workspace_smoke_flow_succeeds_against_test_client(self) -> None:
        result = run_team_workspace_smoke(self.client, suffix="unit-team")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(sorted(result["member_roles"].values()), ["editor", "owner"])
        self.assertEqual(result["versions"], {"created": 1, "teammate_save": 2, "after_notes": 2})
        self.assertEqual(result["note_status_after_reopen"], "open")
        self.assertEqual(result["note_comment_count"], 2)
        self.assertIn("/model/learning_rate", result["diff_paths"])
        self.assertEqual(result["replay_status"], "ok")

        with connect(self.db_path) as conn:
            document = conn.execute(
                "SELECT current_version FROM json_documents WHERE id = ?",
                (result["document_id"],),
            ).fetchone()
            event_count = conn.execute(
                "SELECT COUNT(*) AS count FROM document_events WHERE document_id = ?",
                (result["document_id"],),
            ).fetchone()["count"]
            comment_count = conn.execute("SELECT COUNT(*) AS count FROM comments").fetchone()["count"]

        self.assertEqual(document["current_version"], 2)
        self.assertEqual(event_count, 2)
        self.assertEqual(comment_count, 2)


if __name__ == "__main__":
    unittest.main()
