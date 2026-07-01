from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.backup_scheduler import BackupSchedulerConfig
from app.database import KNOWN_SCHEMA_MIGRATIONS, SCHEMA_SQL, connect, init_db, utc_now
from app.errors import AppError, ErrorCode
from app.health_service import readiness_status, version_status
from app.main import create_app
from app.project_usage_service import ProjectUsageLimitConfig
from app.rate_limit import RateLimitConfig
from app.request_body_limit import RequestBodyLimitConfig
from scripts.smoke_deployment_status import run_deployment_status_report, run_deployment_status_smoke


class DeploymentHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._clear_rate_limit_env()
        self._clear_backup_scheduler_env()
        os.environ.pop("OPENJSON_CORS_ORIGINS", None)
        os.environ.pop("OPENJSON_DEBUG_ERROR_DETAILS", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("OPENJSON_CORS_ORIGINS", None)
        os.environ.pop("OPENJSON_DEBUG_ERROR_DETAILS", None)
        self._clear_rate_limit_env()
        self._clear_backup_scheduler_env()

    def _clear_rate_limit_env(self) -> None:
        os.environ.pop("OPENJSON_RATE_LIMIT_ENABLED", None)
        os.environ.pop("OPENJSON_RATE_LIMIT_REQUESTS", None)
        os.environ.pop("OPENJSON_RATE_LIMIT_WINDOW_SECONDS", None)
        os.environ.pop("OPENJSON_WS_RATE_LIMIT_ENABLED", None)
        os.environ.pop("OPENJSON_WS_RATE_LIMIT_MESSAGES", None)
        os.environ.pop("OPENJSON_WS_RATE_LIMIT_WINDOW_SECONDS", None)
        os.environ.pop("OPENJSON_REQUEST_BODY_LIMIT_ENABLED", None)
        os.environ.pop("OPENJSON_MAX_REQUEST_BODY_BYTES", None)
        os.environ.pop("OPENJSON_PROJECT_USAGE_LIMIT_ENABLED", None)
        os.environ.pop("OPENJSON_MAX_PROJECT_DOCUMENTS", None)
        os.environ.pop("OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES", None)

    def _clear_backup_scheduler_env(self) -> None:
        os.environ.pop("OPENJSON_BACKUP_SCHEDULER_ENABLED", None)
        os.environ.pop("OPENJSON_BACKUP_OUTPUT_DIR", None)
        os.environ.pop("OPENJSON_BACKUP_INTERVAL_SECONDS", None)
        os.environ.pop("OPENJSON_BACKUP_RETENTION_COUNT", None)
        os.environ.pop("OPENJSON_BACKUP_ENCRYPT", None)
        os.environ.pop("OPENJSON_BACKUP_ENCRYPTION_KEY", None)

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
        self.assertFalse(version.json()["runtime_config"]["rate_limit_enabled"])
        self.assertEqual(version.json()["runtime_config"]["rate_limit_requests"], 120)
        self.assertEqual(version.json()["runtime_config"]["rate_limit_window_seconds"], 60)
        self.assertFalse(version.json()["runtime_config"]["websocket_rate_limit_enabled"])
        self.assertEqual(version.json()["runtime_config"]["websocket_rate_limit_messages"], 120)
        self.assertEqual(version.json()["runtime_config"]["websocket_rate_limit_window_seconds"], 60)
        self.assertFalse(version.json()["runtime_config"]["request_body_limit_enabled"])
        self.assertEqual(version.json()["runtime_config"]["max_request_body_bytes"], 10 * 1024 * 1024)
        self.assertFalse(version.json()["runtime_config"]["project_usage_limit_enabled"])
        self.assertEqual(version.json()["runtime_config"]["max_project_documents"], 10000)
        self.assertEqual(version.json()["runtime_config"]["max_project_snapshot_bytes"], 100 * 1024 * 1024)
        self.assertFalse(version.json()["runtime_config"]["backup_scheduler_enabled"])
        self.assertEqual(version.json()["runtime_config"]["backup_scheduler_interval_seconds"], 24 * 60 * 60)
        self.assertEqual(version.json()["runtime_config"]["backup_scheduler_retention_count"], 7)
        self.assertFalse(version.json()["runtime_config"]["backup_scheduler_encrypt"])
        self.assertFalse(version.json()["runtime_config"]["backup_encryption_key_configured"])
        self.assertFalse(version.json()["runtime_config"]["debug_error_details_enabled"])
        self.assertNotIn("do-not-leak", json.dumps(version.json()))
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "ready")
        self.assertTrue(ready.json()["database"]["connected"])
        self.assertTrue(ready.json()["database"]["foreign_keys_enabled"])
        self.assertEqual(ready.json()["database"]["migrations"]["status"], "ok")
        self.assertEqual(ready.json()["operations"]["backup_scheduler"]["status"], "ok")
        self.assertFalse(ready.json()["operations"]["backup_scheduler"]["enabled"])
        self.assertFalse(ready.json()["operations"]["backup_scheduler"]["encryption_key_configured"])
        self.assertEqual(
            ready.json()["database"]["migrations"]["current_schema_version"],
            KNOWN_SCHEMA_MIGRATIONS[-1][0],
        )
        self.assertIn("api_tokens", ready.json()["database"]["required_tables"])
        self.assertIn("user_credentials", ready.json()["database"]["required_tables"])
        self.assertIn("user_sessions", ready.json()["database"]["required_tables"])
        self.assertIn("refresh_tokens", ready.json()["database"]["required_tables"])
        self.assertIn("project_invitations", ready.json()["database"]["required_tables"])
        self.assertIn("email_deliveries", ready.json()["database"]["required_tables"])
        self.assertIn("oidc_states", ready.json()["database"]["required_tables"])
        self.assertIn("offline_sync_operations", ready.json()["database"]["required_tables"])
        self.assertIn("document_events", ready.json()["database"]["required_tables"])
        self.assertIn("document_snapshots", ready.json()["database"]["required_tables"])
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
            payload = version_status(
                allow_actor_header=True,
                cors_origins_configured=False,
                rate_limit_config=RateLimitConfig(enabled=True, requests=77, window_seconds=30),
                websocket_rate_limit_config=RateLimitConfig(enabled=True, requests=33, window_seconds=20),
                request_body_limit_config=RequestBodyLimitConfig(enabled=True, max_bytes=4096),
                project_usage_limit_config=ProjectUsageLimitConfig(
                    enabled=True,
                    max_documents=12,
                    max_snapshot_bytes=65_536,
                ),
                backup_scheduler_config=BackupSchedulerConfig(
                    enabled=True,
                    db_path="/secret/db/path.sqlite3",
                    output_dir="/secret/backups",
                    interval_seconds=86400,
                    retention_count=7,
                    encrypt=True,
                    encryption_key_configured=True,
                ),
            )

        self.assertEqual(payload["source"]["git_commit"], "explicit-sha")
        self.assertEqual(payload["source"]["git_branch"], "release")
        self.assertEqual(payload["source"]["git_repo_slug"], "custom/repo")
        self.assertTrue(payload["runtime_config"]["actor_header_allowed"])
        self.assertTrue(payload["runtime_config"]["rate_limit_enabled"])
        self.assertEqual(payload["runtime_config"]["rate_limit_requests"], 77)
        self.assertEqual(payload["runtime_config"]["rate_limit_window_seconds"], 30)
        self.assertTrue(payload["runtime_config"]["websocket_rate_limit_enabled"])
        self.assertEqual(payload["runtime_config"]["websocket_rate_limit_messages"], 33)
        self.assertEqual(payload["runtime_config"]["websocket_rate_limit_window_seconds"], 20)
        self.assertTrue(payload["runtime_config"]["request_body_limit_enabled"])
        self.assertEqual(payload["runtime_config"]["max_request_body_bytes"], 4096)
        self.assertTrue(payload["runtime_config"]["project_usage_limit_enabled"])
        self.assertEqual(payload["runtime_config"]["max_project_documents"], 12)
        self.assertEqual(payload["runtime_config"]["max_project_snapshot_bytes"], 65_536)
        self.assertTrue(payload["runtime_config"]["backup_scheduler_enabled"])
        self.assertEqual(payload["runtime_config"]["backup_scheduler_interval_seconds"], 86400)
        self.assertEqual(payload["runtime_config"]["backup_scheduler_retention_count"], 7)
        self.assertTrue(payload["runtime_config"]["backup_scheduler_encrypt"])
        self.assertTrue(payload["runtime_config"]["backup_encryption_key_configured"])
        self.assertFalse(payload["runtime_config"]["debug_error_details_enabled"])
        self.assertTrue(payload["runtime_config"]["redis_fanout_enabled"])
        self.assertTrue(payload["runtime_config"]["oidc_configured"])
        self.assertNotIn("secret", json.dumps(payload))
        self.assertNotIn("/secret/db/path.sqlite3", json.dumps(payload))
        self.assertNotIn("/secret/backups", json.dumps(payload))

    def test_unexpected_exception_response_hides_details_by_default(self) -> None:
        app = create_app(self.db_path)

        @app.get("/forced-unexpected-error")
        def forced_unexpected_error() -> dict:
            raise RuntimeError("leaked-secret-token at /data/openjson.sqlite3")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/forced-unexpected-error",
            headers={"X-Request-Id": "req_forced_unexpected"},
        )

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"]["code"], ErrorCode.INTERNAL_ERROR)
        self.assertEqual(body["error"]["message"], "Unexpected internal error.")
        self.assertEqual(body["error"]["details"]["diagnostic_code"], "UNEXPECTED_EXCEPTION")
        self.assertEqual(body["error"]["details"]["request_id"], "req_forced_unexpected")
        self.assertNotIn("message", body["error"]["details"])
        self.assertNotIn("error_type", body["error"]["details"])
        self.assertNotIn("leaked-secret-token", json.dumps(body))
        self.assertNotIn("/data/openjson.sqlite3", json.dumps(body))
        self.assertEqual(response.headers["X-Request-Id"], "req_forced_unexpected")

    def test_unexpected_exception_response_can_include_details_in_debug_mode(self) -> None:
        with patch.dict(os.environ, {"OPENJSON_DEBUG_ERROR_DETAILS": "1"}, clear=False):
            app = create_app(self.db_path)

        @app.get("/forced-debug-error")
        def forced_debug_error() -> dict:
            raise RuntimeError("debug failure detail")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/forced-debug-error")

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"]["code"], ErrorCode.INTERNAL_ERROR)
        self.assertEqual(body["error"]["details"]["diagnostic_code"], "UNEXPECTED_EXCEPTION")
        self.assertEqual(body["error"]["details"]["error_type"], "RuntimeError")
        self.assertEqual(body["error"]["details"]["message"], "debug failure detail")
        self.assertTrue(body["error"]["details"]["request_id"].startswith("req_"))

    def test_rate_limit_returns_standard_error_and_headers(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENJSON_RATE_LIMIT_ENABLED": "1",
                "OPENJSON_RATE_LIMIT_REQUESTS": "2",
                "OPENJSON_RATE_LIMIT_WINDOW_SECONDS": "60",
            },
            clear=False,
        ):
            client = TestClient(create_app(self.db_path))
            first = client.get("/version", headers={"X-Forwarded-For": "203.0.113.10"})
            second = client.get("/version", headers={"X-Forwarded-For": "203.0.113.10"})
            third = client.get(
                "/version",
                headers={
                    "X-Forwarded-For": "203.0.113.10",
                    "X-Request-Id": "req_rate_limited",
                },
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 429)
        self.assertEqual(third.json()["error"]["code"], ErrorCode.RATE_LIMITED)
        self.assertEqual(third.json()["error"]["details"]["limit"], 2)
        self.assertEqual(third.json()["error"]["details"]["window_seconds"], 60)
        self.assertEqual(third.headers["X-RateLimit-Limit"], "2")
        self.assertEqual(third.headers["X-RateLimit-Remaining"], "0")
        self.assertEqual(third.headers["X-Request-Id"], "req_rate_limited")
        self.assertIn("Retry-After", third.headers)

    def test_rate_limit_exempts_health_and_ready(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENJSON_RATE_LIMIT_ENABLED": "1",
                "OPENJSON_RATE_LIMIT_REQUESTS": "1",
                "OPENJSON_RATE_LIMIT_WINDOW_SECONDS": "60",
            },
            clear=False,
        ):
            client = TestClient(create_app(self.db_path))
            health_responses = [client.get("/health") for _ in range(3)]
            ready_responses = [client.get("/ready") for _ in range(3)]
            first_version = client.get("/version", headers={"X-Forwarded-For": "203.0.113.11"})
            second_version = client.get("/version", headers={"X-Forwarded-For": "203.0.113.11"})

        self.assertEqual([response.status_code for response in health_responses], [200, 200, 200])
        self.assertEqual([response.status_code for response in ready_responses], [200, 200, 200])
        self.assertEqual(first_version.status_code, 200)
        self.assertEqual(second_version.status_code, 429)

    def test_request_body_limit_returns_standard_error_before_mutation(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENJSON_REQUEST_BODY_LIMIT_ENABLED": "1",
                "OPENJSON_MAX_REQUEST_BODY_BYTES": "32",
            },
            clear=False,
        ):
            client = TestClient(create_app(self.db_path))
            response = client.post(
                "/users",
                json={
                    "id": "user_large",
                    "email": "large@example.com",
                    "display_name": "Body Limit User",
                },
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.REQUEST_BODY_TOO_LARGE)
        self.assertEqual(response.json()["error"]["details"]["max_request_body_bytes"], 32)
        self.assertEqual(self._counts(), {"documents": 0, "events": 0})

    def test_ready_failure_uses_standard_error_envelope(self) -> None:
        empty_db = str(Path(self.tmp.name) / "empty.sqlite3")

        with self.assertRaises(AppError) as raised:
            readiness_status(empty_db)

        self.assertEqual(raised.exception.code, ErrorCode.INTERNAL_ERROR)
        self.assertEqual(raised.exception.status_code, 503)
        response = raised.exception.as_response()
        self.assertEqual(response["error"]["code"], ErrorCode.INTERNAL_ERROR)
        self.assertIn("missing_tables", response["error"]["details"]["database"])

    def test_ready_failure_reports_encrypted_backup_scheduler_without_key(self) -> None:
        before = self._counts()
        with patch.dict(
            os.environ,
            {
                "OPENJSON_BACKUP_SCHEDULER_ENABLED": "1",
                "OPENJSON_BACKUP_ENCRYPT": "1",
            },
            clear=False,
        ):
            client = TestClient(create_app(self.db_path))
            response = client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.INTERNAL_ERROR)
        self.assertEqual(response.json()["error"]["details"]["database"]["migrations"]["status"], "ok")
        backup_status = response.json()["error"]["details"]["operations"]["backup_scheduler"]
        self.assertEqual(backup_status["status"], "misconfigured")
        self.assertTrue(backup_status["enabled"])
        self.assertTrue(backup_status["encrypt"])
        self.assertFalse(backup_status["encryption_key_configured"])
        self.assertIn("OPENJSON_BACKUP_ENCRYPTION_KEY", backup_status["message"])
        self.assertNotIn("db_path", backup_status)
        self.assertNotIn("output_dir", backup_status)
        self.assertEqual(self._counts(), before)

    def test_ready_failure_reports_pending_migrations(self) -> None:
        pending_db = str(Path(self.tmp.name) / "pending.sqlite3")
        with connect(pending_db) as conn:
            conn.executescript(SCHEMA_SQL)

        with self.assertRaises(AppError) as raised:
            readiness_status(pending_db)

        response = raised.exception.as_response()
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(response["error"]["code"], ErrorCode.INTERNAL_ERROR)
        self.assertEqual(response["error"]["details"]["database"]["missing_tables"], [])
        migrations = response["error"]["details"]["database"]["migrations"]
        self.assertEqual(migrations["status"], "pending")
        self.assertEqual(migrations["applied_count"], 0)
        self.assertEqual(migrations["pending_migrations"], [migration_id for migration_id, _ in KNOWN_SCHEMA_MIGRATIONS])

    def test_ready_failure_reports_migration_drift(self) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO schema_migrations (id, description, applied_at)
                VALUES (?, ?, ?)
                """,
                ("9999_unknown_ready_drift", "Unexpected readiness drift.", utc_now()),
            )

        client = TestClient(create_app(self.db_path))
        response = client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], ErrorCode.INTERNAL_ERROR)
        migrations = response.json()["error"]["details"]["database"]["migrations"]
        self.assertEqual(migrations["status"], "drift")
        self.assertEqual(migrations["unknown_migrations"], ["9999_unknown_ready_drift"])

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
        self.assertIn("document_snapshots", second_payload["tables"])
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
        self.assertIn("OPENJSON_DEBUG_ERROR_DETAILS", render_yaml)
        self.assertIn('value: "0"', render_yaml)
        self.assertIn("OPENJSON_RATE_LIMIT_ENABLED", render_yaml)
        self.assertIn("OPENJSON_RATE_LIMIT_REQUESTS", render_yaml)
        self.assertIn("OPENJSON_WS_RATE_LIMIT_ENABLED", render_yaml)
        self.assertIn("OPENJSON_WS_RATE_LIMIT_MESSAGES", render_yaml)
        self.assertIn("OPENJSON_REQUEST_BODY_LIMIT_ENABLED", render_yaml)
        self.assertIn("OPENJSON_MAX_REQUEST_BODY_BYTES", render_yaml)
        self.assertIn("OPENJSON_PROJECT_USAGE_LIMIT_ENABLED", render_yaml)
        self.assertIn("OPENJSON_MAX_PROJECT_DOCUMENTS", render_yaml)
        self.assertIn("OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES", render_yaml)
        self.assertIn("OPENJSON_BACKUP_SCHEDULER_ENABLED", render_yaml)
        self.assertIn("OPENJSON_BACKUP_OUTPUT_DIR", render_yaml)
        self.assertIn("OPENJSON_BACKUP_INTERVAL_SECONDS", render_yaml)
        self.assertIn("OPENJSON_BACKUP_RETENTION_COUNT", render_yaml)
        self.assertIn("OPENJSON_BACKUP_ENCRYPT", render_yaml)
        self.assertIn("OPENJSON_BACKUP_ENCRYPTION_KEY", render_yaml)

    def test_deployment_status_smoke_runner_uses_public_read_only_surfaces(self) -> None:
        before = self._counts()
        with patch.dict(
            os.environ,
            {
                "OPENJSON_GIT_COMMIT": "smoke-sha",
                "OPENJSON_ALLOW_ACTOR_HEADER": "0",
                "OPENJSON_RATE_LIMIT_ENABLED": "1",
                "OPENJSON_RATE_LIMIT_REQUESTS": "10",
                "OPENJSON_RATE_LIMIT_WINDOW_SECONDS": "60",
                "OPENJSON_WS_RATE_LIMIT_ENABLED": "1",
                "OPENJSON_WS_RATE_LIMIT_MESSAGES": "10",
                "OPENJSON_WS_RATE_LIMIT_WINDOW_SECONDS": "60",
                "OPENJSON_REQUEST_BODY_LIMIT_ENABLED": "1",
                "OPENJSON_MAX_REQUEST_BODY_BYTES": "10485760",
                "OPENJSON_PROJECT_USAGE_LIMIT_ENABLED": "1",
                "OPENJSON_MAX_PROJECT_DOCUMENTS": "10000",
                "OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES": "104857600",
                "OPENJSON_BACKUP_SCHEDULER_ENABLED": "1",
                "OPENJSON_BACKUP_INTERVAL_SECONDS": "86400",
                "OPENJSON_BACKUP_RETENTION_COUNT": "7",
                "OPENJSON_BACKUP_ENCRYPT": "1",
                "OPENJSON_BACKUP_ENCRYPTION_KEY": "test-key-configured",
            },
            clear=False,
        ):
            client = TestClient(create_app(self.db_path))
            result = run_deployment_status_smoke(
                client,
                expect_commit="smoke",
                expect_actor_header_allowed=False,
                expect_backup_scheduler_enabled=True,
                expect_backup_encryption_key_configured=True,
                expect_debug_error_details_enabled=False,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["ready"]["database"]["migrations"]["status"], "ok")
        self.assertEqual(result["version"]["source"]["git_commit"], "smoke-sha")
        self.assertTrue(result["version"]["runtime_config"]["rate_limit_enabled"])
        self.assertTrue(result["version"]["runtime_config"]["websocket_rate_limit_enabled"])
        self.assertTrue(result["version"]["runtime_config"]["request_body_limit_enabled"])
        self.assertTrue(result["version"]["runtime_config"]["project_usage_limit_enabled"])
        self.assertTrue(result["version"]["runtime_config"]["backup_scheduler_enabled"])
        self.assertTrue(result["version"]["runtime_config"]["backup_scheduler_encrypt"])
        self.assertTrue(result["version"]["runtime_config"]["backup_encryption_key_configured"])
        self.assertFalse(result["version"]["runtime_config"]["debug_error_details_enabled"])
        self.assertFalse(result["version"]["runtime_config"]["actor_header_allowed"])
        self.assertTrue(result["app"]["contains_openjson"])
        self.assertEqual(self._counts(), before)

    def test_deployment_status_report_returns_structured_404_diagnostic(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok", "service": "openjson-api"})
            if request.url.path == "/ready":
                return httpx.Response(
                    200,
                    json={
                        "status": "ready",
                        "database": {
                            "migrations": {
                                "status": "ok",
                            },
                        },
                    },
                )
            if request.url.path == "/app":
                return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>OpenJson</title>")
            return httpx.Response(404, json={"detail": "Not Found"})

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport, base_url="https://openjson.example") as client:
            result = run_deployment_status_report(client)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["checks"]["version"]["http_status"], 404)
        self.assertEqual(
            [diagnostic["code"] for diagnostic in result["diagnostics"]],
            ["VERSION_ENDPOINT_NOT_FOUND"],
        )
        self.assertIn(
            "manual Render deploy",
            result["diagnostics"][0]["message"],
        )

    def test_deployment_status_report_detects_stale_ready_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok", "service": "openjson-api"})
            if request.url.path == "/ready":
                return httpx.Response(
                    200,
                    json={
                        "status": "ready",
                        "database": {
                            "connected": True,
                            "foreign_keys_enabled": True,
                        },
                    },
                )
            if request.url.path == "/version":
                return httpx.Response(
                    200,
                    json={
                        "service": "openjson-api",
                        "source": {
                            "git_commit": "abc123",
                        },
                        "runtime_config": {
                            "actor_header_allowed": False,
                        },
                    },
                )
            return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>OpenJson</title>")

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport, base_url="https://openjson.example") as client:
            result = run_deployment_status_report(client)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [diagnostic["code"] for diagnostic in result["diagnostics"]],
            ["READINESS_MIGRATION_STATUS_MISSING"],
        )
        self.assertIn(
            "older build",
            result["diagnostics"][0]["message"],
        )

    def test_deployment_status_report_detects_backup_scheduler_mismatch(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok", "service": "openjson-api"})
            if request.url.path == "/ready":
                return httpx.Response(
                    200,
                    json={
                        "status": "ready",
                        "database": {
                            "migrations": {
                                "status": "ok",
                            },
                        },
                    },
                )
            if request.url.path == "/version":
                return httpx.Response(
                    200,
                    json={
                        "service": "openjson-api",
                        "source": {
                            "git_commit": "abc123",
                        },
                        "runtime_config": {
                            "actor_header_allowed": False,
                            "backup_scheduler_enabled": False,
                        },
                    },
                )
            return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>OpenJson</title>")

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport, base_url="https://openjson.example") as client:
            result = run_deployment_status_report(client, expect_backup_scheduler_enabled=True)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [diagnostic["code"] for diagnostic in result["diagnostics"]],
            ["BACKUP_SCHEDULER_CONFIG_MISMATCH"],
        )

    def test_deployment_status_report_detects_backup_key_mismatch(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok", "service": "openjson-api"})
            if request.url.path == "/ready":
                return httpx.Response(
                    200,
                    json={
                        "status": "ready",
                        "database": {
                            "migrations": {
                                "status": "ok",
                            },
                        },
                    },
                )
            if request.url.path == "/version":
                return httpx.Response(
                    200,
                    json={
                        "service": "openjson-api",
                        "source": {
                            "git_commit": "abc123",
                        },
                        "runtime_config": {
                            "actor_header_allowed": False,
                            "backup_scheduler_enabled": True,
                            "backup_encryption_key_configured": False,
                        },
                    },
                )
            return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>OpenJson</title>")

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport, base_url="https://openjson.example") as client:
            result = run_deployment_status_report(
                client,
                expect_backup_scheduler_enabled=True,
                expect_backup_encryption_key_configured=True,
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [diagnostic["code"] for diagnostic in result["diagnostics"]],
            ["BACKUP_ENCRYPTION_KEY_CONFIG_MISMATCH"],
        )

    def test_deployment_status_report_detects_debug_error_details_mismatch(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok", "service": "openjson-api"})
            if request.url.path == "/ready":
                return httpx.Response(
                    200,
                    json={
                        "status": "ready",
                        "database": {
                            "migrations": {
                                "status": "ok",
                            },
                        },
                    },
                )
            if request.url.path == "/version":
                return httpx.Response(
                    200,
                    json={
                        "service": "openjson-api",
                        "source": {
                            "git_commit": "abc123",
                        },
                        "runtime_config": {
                            "actor_header_allowed": False,
                            "backup_scheduler_enabled": True,
                            "backup_encryption_key_configured": True,
                            "debug_error_details_enabled": True,
                        },
                    },
                )
            return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>OpenJson</title>")

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport, base_url="https://openjson.example") as client:
            result = run_deployment_status_report(client, expect_debug_error_details_enabled=False)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [diagnostic["code"] for diagnostic in result["diagnostics"]],
            ["DEBUG_ERROR_DETAILS_CONFIG_MISMATCH"],
        )

    def test_deployment_status_report_detects_ready_backup_scheduler_misconfiguration(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok", "service": "openjson-api"})
            if request.url.path == "/ready":
                return httpx.Response(
                    503,
                    json={
                        "error": {
                            "code": ErrorCode.INTERNAL_ERROR,
                            "message": "Readiness check failed.",
                            "details": {
                                "database": {
                                    "connected": True,
                                    "foreign_keys_enabled": True,
                                    "missing_tables": [],
                                    "migrations": {
                                        "status": "ok",
                                    },
                                },
                                "operations": {
                                    "backup_scheduler": {
                                        "status": "misconfigured",
                                        "enabled": True,
                                        "encrypt": True,
                                        "encryption_key_configured": False,
                                    },
                                },
                            },
                        },
                    },
                )
            if request.url.path == "/version":
                return httpx.Response(
                    200,
                    json={
                        "service": "openjson-api",
                        "source": {
                            "git_commit": "abc123",
                        },
                        "runtime_config": {
                            "actor_header_allowed": False,
                            "backup_scheduler_enabled": True,
                            "backup_encryption_key_configured": False,
                        },
                    },
                )
            return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>OpenJson</title>")

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport, base_url="https://openjson.example") as client:
            result = run_deployment_status_report(client)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            [diagnostic["code"] for diagnostic in result["diagnostics"]],
            ["READY_BACKUP_SCHEDULER_MISCONFIGURED"],
        )
        self.assertIn("OPENJSON_BACKUP_ENCRYPTION_KEY", result["diagnostics"][0]["message"])


if __name__ == "__main__":
    unittest.main()
