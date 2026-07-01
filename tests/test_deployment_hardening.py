from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import init_db
from app.errors import AppError, ErrorCode
from app.health_service import readiness_status
from app.main import create_app


class DeploymentHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("OPENJSON_CORS_ORIGINS", None)

    def test_health_and_ready_endpoints_are_public(self) -> None:
        client = TestClient(create_app(self.db_path))

        health = client.get("/health")
        ready = client.get("/ready")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(health.json()["service"], "openjson-api")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "ready")
        self.assertTrue(ready.json()["database"]["connected"])
        self.assertTrue(ready.json()["database"]["foreign_keys_enabled"])
        self.assertIn("api_tokens", ready.json()["database"]["required_tables"])
        self.assertIn("user_credentials", ready.json()["database"]["required_tables"])
        self.assertIn("user_sessions", ready.json()["database"]["required_tables"])
        self.assertIn("refresh_tokens", ready.json()["database"]["required_tables"])
        self.assertIn("project_invitations", ready.json()["database"]["required_tables"])
        self.assertIn("email_deliveries", ready.json()["database"]["required_tables"])
        self.assertIn("oidc_states", ready.json()["database"]["required_tables"])
        self.assertIn("offline_sync_operations", ready.json()["database"]["required_tables"])
        self.assertIn("document_events", ready.json()["database"]["required_tables"])
        self.assertIn("audit_log", ready.json()["database"]["required_tables"])
        self.assertIn("schema_migrations", ready.json()["database"]["required_tables"])

    def test_ready_failure_uses_standard_error_envelope(self) -> None:
        empty_db = str(Path(self.tmp.name) / "empty.sqlite3")

        with self.assertRaises(AppError) as raised:
            readiness_status(empty_db)

        self.assertEqual(raised.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(raised.exception.status_code, 503)
        response = raised.exception.as_response()
        self.assertEqual(response["error"]["code"], ErrorCode.INTERNAL_ERROR)
        self.assertIn("missing_tables", response["error"]["details"]["database"])

    def test_init_db_script_is_idempotent(self) -> None:
        script_db = str(Path(self.tmp.name) / "script.sqlite3")
        root = Path(__file__).resolve().parents[1]

        first = subprocess.run(
            [sys.executable, "scripts/init_db.py", "--db-path", script_db],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        second = subprocess.run(
            [sys.executable, "scripts/init_db.py", "--db-path", script_db],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )

        first_payload = json.loads(first.stdout)
        second_payload = json.loads(second.stdout)
        self.assertEqual(first_payload["status"], "initialized")
        self.assertEqual(second_payload["status"], "initialized")
        self.assertTrue(second_payload["foreign_keys_enabled"])
        self.assertIn("api_tokens", second_payload["tables"])
        self.assertIn("document_events", second_payload["tables"])
        self.assertIn("audit_log", second_payload["tables"])
        self.assertIn("schema_migrations", second_payload["tables"])
        self.assertEqual(second_payload["migrations"]["status"], "ok")

    def test_cors_origins_are_configured_only_when_env_is_set(self) -> None:
        os.environ["OPENJSON_CORS_ORIGINS"] = "http://localhost:3000,https://example.com"
        client = TestClient(create_app(self.db_path))

        preflight = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers["access-control-allow-origin"], "http://localhost:3000")

    def test_deployment_runtime_files_exist_without_local_db_artifacts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")
        render_yaml = (root / "render.yaml").read_text(encoding="utf-8")

        self.assertIn("uvicorn", dockerfile)
        self.assertIn("OPENJSON_DB_PATH", dockerfile)
        self.assertIn("*.sqlite3", dockerignore)
        self.assertIn("__pycache__/", dockerignore)
        self.assertIn("OPENJSON_ALLOW_ACTOR_HEADER", render_yaml)
        self.assertIn('value: "0"', render_yaml)


if __name__ == "__main__":
    unittest.main()
