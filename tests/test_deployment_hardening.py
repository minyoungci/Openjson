from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import init_db
from app.errors import AppError, ErrorCode
from app.health_service import readiness_status, version_status
from app.main import create_app
from scripts.smoke_deployment_status import run_deployment_status_smoke


class DeploymentHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("OPENJSON_CORS_ORIGINS", None)

    def _counts(self) -> dict[str, int]:
        from app.database import connect

        with connect(self.db_path) as conn:
            return {
                "documents": conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"],
                "events": conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"],
            }

    def test_health_ready_and_version_endpoints_are_public(self) -> None:
        before = self._counts()
        env = {
            "RENDER": "true",
            "RENDER_GIT_COMMIT": "abc123",
            "RENDER_GIT_BRANCH": "main",
            "RENDER_GIT_REPO_SLUG": "minyoungci/Openjson",
            "RENDER_SERVICE_NAME": "openjson",
            "RENDER_SERVICE_TYPE": "web",
            "RENDER_EXTERNAL_HOSTNAME": "openjson-test.onrender.com",
            "OPENJSON_ALLOW_ACTOR_HEADER": "0",
            "OPENJSON_CORS_ORIGINS": "https://openjson.thelumen.work",
            "OPENJSON_EMAIL_BACKEND": "console",
            "OPENJSON_SMTP_PASSWORD": "do-not-leak",
        }
        with patch.dict(os.environ, env, clear=False):
            client = TestClient(create_app(self.db_path))

            health = client.get("/health", headers={"X-Actor-Id": "spoofed"})
            version = client.get("/version", headers={"X-Actor-Id": "spoofed"})
            ready = client.get("/ready")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(health.json()["service"], "openjson-api")
        self.assertEqual(version.status_code, 200)
        self.assertEqual(version.json()["deployment"]["platform"], "render")
        self.assertEqual(version.json()["deployment"]["service_name"], "openjson")
        self.assertEqual(version.json()["deployment"]["service_type"], "web")
        self.assertEqual(version.json()["source"]["git_commit"], "abc123")
        self.assertEqual(version.json()["source"]["git_branch"], "main")
        self.assertEqual(version.json()["source"]["git_repo_slug"], "minyoungci/Openjson")
        self.assertFalse(version.json()["runtime_config"]["actor_header_allowed"])
        self.assertTrue(version.json()["runtime_config"]["cors_origins_configured"])
        self.assertEqual(version.json()["runtime_config"]["email_backend"], "console")
        self.assertNotIn("do-not-leak", json.dumps(version.json()))
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
        self.assertEqual(self._counts(), before)

    def test_version_status_prefers_explicit_openjson_git_metadata(self) -> None:
        env = {
            "OPENJSON_GIT_COMMIT": "explicit-sha",
            "OPENJSON_GIT_BRANCH": "release",
            "OPENJSON_GIT_REPO_SLUG": "custom/repo",
            "RENDER_GIT_COMMIT": "render-sha",
            "RENDER_GIT_BRANCH": "main",
            "RENDER_GIT_REPO_SLUG": "render/repo",
            "OPENJSON_REDIS_URL": "redis://example",
            "OPENJSON_OIDC_ISSUER": "https://issuer.example",
            "OPENJSON_OIDC_CLIENT_ID": "client",
            "OPENJSON_OIDC_CLIENT_SECRET": "secret",
            "OPENJSON_OIDC_REDIRECT_URI": "https://openjson.example/auth/oidc/callback",
        }
        with patch.dict(os.environ, env, clear=False):
            payload = version_status(allow_actor_header=True, cors_origins_configured=False)

        self.assertEqual(payload["source"]["git_commit"], "explicit-sha")
        self.assertEqual(payload["source"]["git_branch"], "release")
        self.assertEqual(payload["source"]["git_repo_slug"], "custom/repo")
        self.assertTrue(payload["runtime_config"]["actor_header_allowed"])
        self.assertTrue(payload["runtime_config"]["redis_fanout_enabled"])
        self.assertTrue(payload["runtime_config"]["oidc_configured"])
        self.assertNotIn("secret", json.dumps(payload))

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

    def test_deployment_status_smoke_runner_uses_public_read_only_surfaces(self) -> None:
        before = self._counts()
        with patch.dict(
            os.environ,
            {
                "OPENJSON_GIT_COMMIT": "smoke-sha",
                "OPENJSON_ALLOW_ACTOR_HEADER": "0",
            },
            clear=False,
        ):
            client = TestClient(create_app(self.db_path))
            result = run_deployment_status_smoke(
                client,
                expect_commit="smoke",
                expect_actor_header_allowed=False,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["version"]["source"]["git_commit"], "smoke-sha")
        self.assertFalse(result["version"]["runtime_config"]["actor_header_allowed"])
        self.assertTrue(result["app"]["contains_openjson"])
        self.assertEqual(self._counts(), before)


if __name__ == "__main__":
    unittest.main()
