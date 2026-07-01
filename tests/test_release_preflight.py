from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.release_preflight import build_release_preflight_report


def _ok(stdout: str = "") -> dict[str, Any]:
    return {
        "ok": True,
        "returncode": 0,
        "stdout": stdout,
        "stderr": "",
    }


def _write_runtime_files(root: Path, *, render_yaml: str | None = None) -> None:
    (root / "scripts").mkdir()
    (root / "Dockerfile").write_text("FROM python:3.13-slim\n", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi==0.135.2\n", encoding="utf-8")
    (root / "scripts" / "smoke_deployment_status.py").write_text("# smoke\n", encoding="utf-8")
    (root / "scripts" / "migrate_db.py").write_text("# migrate\n", encoding="utf-8")
    (root / "scripts" / "check_replay_consistency.py").write_text("# replay\n", encoding="utf-8")
    (root / "scripts" / "check_event_chain_integrity.py").write_text("# event chain\n", encoding="utf-8")
    (root / "scripts" / "check_database_integrity.py").write_text("# integrity\n", encoding="utf-8")
    (root / "scripts" / "backup_crypto.py").write_text("# backup crypto\n", encoding="utf-8")
    (root / "scripts" / "backup_sqlite.py").write_text("# backup\n", encoding="utf-8")
    (root / "scripts" / "restore_sqlite.py").write_text("# restore\n", encoding="utf-8")
    (root / "scripts" / "backup_restore_drill.py").write_text("# drill\n", encoding="utf-8")
    (root / "render.yaml").write_text(
        render_yaml
        or """
services:
  - type: web
    name: openjson
    runtime: docker
    plan: starter
    autoDeploy: false
    numInstances: 1
    healthCheckPath: /health
    disk:
      mountPath: /data
    envVars:
      - key: OPENJSON_DB_PATH
        value: /data/openjson.sqlite3
      - key: OPENJSON_PUBLIC_BASE_URL
        value: https://openjson.thelumen.work
      - key: OPENJSON_CORS_ORIGINS
        value: https://openjson.thelumen.work
      - key: OPENJSON_ALLOW_ACTOR_HEADER
        value: "0"
      - key: OPENJSON_RATE_LIMIT_ENABLED
        value: "1"
      - key: OPENJSON_WS_RATE_LIMIT_ENABLED
        value: "1"
      - key: OPENJSON_REQUEST_BODY_LIMIT_ENABLED
        value: "1"
      - key: OPENJSON_PROJECT_USAGE_LIMIT_ENABLED
        value: "1"
""",
        encoding="utf-8",
    )


def _git_runner(*, dirty: bool = False, branch: str = "main", sync_status: str = "## main...origin/main"):
    def run(args: list[str], cwd: Path) -> dict[str, Any]:
        command = tuple(args[1:])
        if command == ("status", "--short"):
            return _ok(" M app/main.py" if dirty else "")
        if command == ("status", "-sb"):
            return _ok(sync_status)
        if command == ("branch", "--show-current"):
            return _ok(branch)
        if command == ("rev-parse", "--short", "HEAD"):
            return _ok("abc123")
        if command == ("rev-parse", "HEAD"):
            return _ok("abc123def456")
        if command == ("remote", "get-url", "origin"):
            return _ok("https://github.com/minyoungci/Openjson.git")
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": "unexpected command"}

    return run


class ReleasePreflightTests(unittest.TestCase):
    def test_preflight_passes_for_clean_main_blueprint_without_deployment_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_files(root)

            report = build_release_preflight_report(root, git_runner=_git_runner())

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["latest_commit_short"], "abc123")
        self.assertEqual(report["checks"]["git_clean"]["status"], "ok")
        self.assertEqual(report["checks"]["render_blueprint"]["status"], "ok")
        self.assertIn(
            "scripts/backup_restore_drill.py",
            report["checks"]["required_files"]["details"]["required_operation_files"],
        )
        self.assertIn("release_preflight.py", report["summary"]["next_actions"][0])

    def test_preflight_fails_when_backup_restore_drill_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_files(root)
            (root / "scripts" / "backup_restore_drill.py").unlink()

            report = build_release_preflight_report(root, git_runner=_git_runner())

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"]["required_files"]["status"], "failed")
        self.assertIn(
            "scripts/backup_restore_drill.py",
            report["checks"]["required_files"]["details"]["missing"],
        )
        self.assertTrue(
            any("operations files" in action for action in report["summary"]["next_actions"]),
            report["summary"]["next_actions"],
        )

    def test_preflight_fails_dirty_worktree_before_deploy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_files(root)

            report = build_release_preflight_report(root, git_runner=_git_runner(dirty=True))

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"]["git_clean"]["status"], "failed")
        self.assertIn("Commit or stash", report["summary"]["next_actions"][0])

    def test_preflight_fails_when_render_blueprint_lacks_required_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_files(
                root,
                render_yaml="""
services:
  - type: web
    name: openjson
    runtime: docker
    plan: starter
    autoDeploy: false
    numInstances: 1
    healthCheckPath: /health
""",
            )

            report = build_release_preflight_report(root, git_runner=_git_runner())

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"]["render_blueprint"]["status"], "failed")
        missing_keys = {item["key"] for item in report["checks"]["render_blueprint"]["details"]["missing"]}
        self.assertIn("db_path", missing_keys)
        self.assertIn("actor_header_value", missing_keys)

    def test_preflight_reports_stale_official_deployment_action(self) -> None:
        captured: dict[str, Any] = {}

        def deployment_runner(
            base_url: str,
            expect_commit: str | None,
            expect_actor_header_allowed: bool | None,
        ) -> dict[str, Any]:
            captured.update(
                {
                    "base_url": base_url,
                    "expect_commit": expect_commit,
                    "expect_actor_header_allowed": expect_actor_header_allowed,
                }
            )
            return {
                "status": "failed",
                "diagnostics": [
                    {
                        "code": "VERSION_ENDPOINT_NOT_FOUND",
                        "message": "older build",
                        "details": {},
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_runtime_files(root)

            report = build_release_preflight_report(
                root,
                base_url="https://openjson.thelumen.work",
                expect_actor_header_allowed=False,
                git_runner=_git_runner(),
                deployment_runner=deployment_runner,
            )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(captured["expect_commit"], "abc123")
        self.assertFalse(captured["expect_actor_header_allowed"])
        self.assertEqual(report["checks"]["deployment_status"]["status"], "failed")
        self.assertEqual(report["checks"]["deployment_status"]["message"], "Deployment status smoke failed.")
        self.assertTrue(
            any("Manual Deploy" in action for action in report["summary"]["next_actions"]),
            report["summary"]["next_actions"],
        )


if __name__ == "__main__":
    unittest.main()
