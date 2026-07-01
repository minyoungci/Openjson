from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.smoke_deployment_status import run_deployment_status_report


CommandRunner = Callable[[list[str], Path], dict[str, Any]]
DeploymentRunner = Callable[[str, str | None, bool | None], dict[str, Any]]


REQUIRED_FILES = (
    "Dockerfile",
    "render.yaml",
    "requirements.txt",
    "scripts/smoke_deployment_status.py",
    "scripts/migrate_db.py",
)

REQUIRED_RENDER_SNIPPETS = {
    "docker_runtime": "runtime: docker",
    "starter_plan": "plan: starter",
    "manual_deploy": "autoDeploy: false",
    "single_instance": "numInstances: 1",
    "health_check": "healthCheckPath: /health",
    "persistent_disk": "mountPath: /data",
    "db_path": "OPENJSON_DB_PATH",
    "public_base_url": "OPENJSON_PUBLIC_BASE_URL",
    "cors_origins": "OPENJSON_CORS_ORIGINS",
    "actor_header_disabled": "OPENJSON_ALLOW_ACTOR_HEADER",
    "http_rate_limit": "OPENJSON_RATE_LIMIT_ENABLED",
    "websocket_rate_limit": "OPENJSON_WS_RATE_LIMIT_ENABLED",
    "request_body_limit": "OPENJSON_REQUEST_BODY_LIMIT_ENABLED",
    "project_usage_limit": "OPENJSON_PROJECT_USAGE_LIMIT_ENABLED",
}


def _run_command(args: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _check(status: bool, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "ok" if status else "failed",
        "message": message,
        "details": details or {},
    }


def _git_value(git_runner: CommandRunner, repo_root: Path, args: list[str]) -> dict[str, Any]:
    return git_runner(["git", *args], repo_root)


def _build_git_checks(repo_root: Path, git_runner: CommandRunner) -> tuple[dict[str, Any], dict[str, Any]]:
    status_short = _git_value(git_runner, repo_root, ["status", "--short"])
    status_branch = _git_value(git_runner, repo_root, ["status", "-sb"])
    branch = _git_value(git_runner, repo_root, ["branch", "--show-current"])
    short_commit = _git_value(git_runner, repo_root, ["rev-parse", "--short", "HEAD"])
    full_commit = _git_value(git_runner, repo_root, ["rev-parse", "HEAD"])
    origin = _git_value(git_runner, repo_root, ["remote", "get-url", "origin"])

    branch_name = branch["stdout"] if branch["ok"] else ""
    status_header = status_branch["stdout"].splitlines()[0] if status_branch["stdout"] else ""
    is_ahead = "[ahead" in status_header
    is_behind = "[behind" in status_header
    has_diverged = "[ahead" in status_header and "behind" in status_header
    origin_url = origin["stdout"] if origin["ok"] else ""
    expected_repo = "minyoungci/openjson"

    checks = {
        "git_available": _check(
            all(result["ok"] for result in (status_short, status_branch, branch, short_commit, full_commit, origin)),
            "Git metadata is readable.",
            {
                "status_short_returncode": status_short["returncode"],
                "status_branch_returncode": status_branch["returncode"],
                "branch_returncode": branch["returncode"],
                "commit_returncode": full_commit["returncode"],
                "origin_returncode": origin["returncode"],
            },
        ),
        "git_clean": _check(
            status_short["ok"] and status_short["stdout"] == "",
            "Worktree has no uncommitted changes.",
            {"status_short": status_short["stdout"]},
        ),
        "git_branch": _check(
            branch_name == "main",
            "Current branch is main.",
            {"branch": branch_name},
        ),
        "git_sync": _check(
            status_branch["ok"] and not is_ahead and not is_behind and not has_diverged,
            "Current branch is not ahead or behind its upstream.",
            {"status": status_header},
        ),
        "git_remote": _check(
            origin["ok"] and expected_repo in origin_url.lower(),
            "Origin remote points at minyoungci/Openjson.",
            {"origin": origin_url},
        ),
    }
    summary = {
        "current_branch": branch_name,
        "latest_commit": full_commit["stdout"] if full_commit["ok"] else None,
        "latest_commit_short": short_commit["stdout"] if short_commit["ok"] else None,
        "origin": origin_url,
        "upstream_status": status_header,
    }
    return checks, summary


def _build_required_file_check(repo_root: Path) -> dict[str, Any]:
    missing = [relative for relative in REQUIRED_FILES if not (repo_root / relative).exists()]
    return _check(
        not missing,
        "Required deployment files are present.",
        {
            "required_files": list(REQUIRED_FILES),
            "missing": missing,
        },
    )


def _build_render_blueprint_check(repo_root: Path) -> dict[str, Any]:
    render_yaml = repo_root / "render.yaml"
    if not render_yaml.exists():
        return _check(False, "render.yaml is present and contains required deployment settings.", {"missing": True})

    text = render_yaml.read_text(encoding="utf-8")
    missing = [
        {"key": key, "snippet": snippet}
        for key, snippet in REQUIRED_RENDER_SNIPPETS.items()
        if snippet not in text
    ]
    actor_header_is_disabled = "OPENJSON_ALLOW_ACTOR_HEADER" in text and 'value: "0"' in text
    if not actor_header_is_disabled:
        missing.append({"key": "actor_header_value", "snippet": 'OPENJSON_ALLOW_ACTOR_HEADER value: "0"'})

    return _check(
        not missing,
        "Render Blueprint contains required single-instance production guard settings.",
        {
            "missing": missing,
            "checked_snippets": REQUIRED_RENDER_SNIPPETS,
        },
    )


def _run_deployment(base_url: str, expect_commit: str | None, expect_actor_header_allowed: bool | None) -> dict[str, Any]:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=20.0, follow_redirects=True) as client:
        return run_deployment_status_report(
            client,
            expect_commit=expect_commit,
            expect_actor_header_allowed=expect_actor_header_allowed,
        )


def _deployment_check(
    base_url: str,
    expect_commit: str | None,
    expect_actor_header_allowed: bool | None,
    deployment_runner: DeploymentRunner,
) -> dict[str, Any]:
    try:
        report = deployment_runner(base_url, expect_commit, expect_actor_header_allowed)
    except Exception as exc:  # pragma: no cover - depends on external network failures
        return _check(
            False,
            "Deployment status smoke could not reach the public service.",
            {"base_url": base_url, "error": str(exc)},
        )
    passed = report.get("status") == "ok"
    return _check(
        passed,
        "Deployment status smoke passed." if passed else "Deployment status smoke failed.",
        {
            "base_url": base_url,
            "report": report,
        },
    )


def _next_actions(checks: dict[str, Any], *, base_url: str | None, latest_commit_short: str | None) -> list[str]:
    actions: list[str] = []
    if checks.get("git_clean", {}).get("status") != "ok":
        actions.append("Commit or stash local changes before deploying.")
    if checks.get("git_branch", {}).get("status") != "ok":
        actions.append("Switch to the main branch before using the Render Blueprint deployment.")
    if checks.get("git_sync", {}).get("status") != "ok":
        actions.append("Push/pull main until it is in sync with origin before deploying.")
    if checks.get("git_remote", {}).get("status") != "ok":
        actions.append("Verify the origin remote points at https://github.com/minyoungci/Openjson.git.")
    if checks.get("required_files", {}).get("status") != "ok":
        actions.append("Restore missing deployment files before deploying.")
    if checks.get("render_blueprint", {}).get("status") != "ok":
        actions.append("Fix render.yaml before applying or redeploying the Render service.")

    deployment = checks.get("deployment_status")
    if deployment and deployment.get("status") != "ok":
        diagnostics = deployment.get("details", {}).get("report", {}).get("diagnostics", [])
        diagnostic_codes = [item.get("code") for item in diagnostics if isinstance(item, dict)]
        if "VERSION_ENDPOINT_NOT_FOUND" in diagnostic_codes or "READINESS_MIGRATION_STATUS_MISSING" in diagnostic_codes:
            actions.append(
                "Open Render Dashboard -> openjson -> Manual Deploy -> Deploy latest commit, then rerun this preflight."
            )
        else:
            actions.append("Inspect the deployment_status diagnostics and fix the public service before sharing the URL.")
    elif base_url is None:
        commit_flag = latest_commit_short or "<git-sha>"
        actions.append(
            "After the manual Render deploy, run: "
            f"python scripts\\release_preflight.py --base-url https://openjson.thelumen.work "
            f"--expect-commit {commit_flag} --expect-actor-header-allowed false"
        )

    return actions


def build_release_preflight_report(
    repo_root: str | Path,
    *,
    base_url: str | None = None,
    expect_commit: str | None = None,
    expect_actor_header_allowed: bool | None = None,
    git_runner: CommandRunner = _run_command,
    deployment_runner: DeploymentRunner = _run_deployment,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    git_checks, git_summary = _build_git_checks(root, git_runner)
    checks = {
        **git_checks,
        "required_files": _build_required_file_check(root),
        "render_blueprint": _build_render_blueprint_check(root),
    }

    effective_expect_commit = expect_commit
    if base_url and effective_expect_commit is None:
        effective_expect_commit = git_summary.get("latest_commit_short")
    if base_url:
        checks["deployment_status"] = _deployment_check(
            base_url,
            effective_expect_commit,
            expect_actor_header_allowed,
            deployment_runner,
        )

    status = "ok" if all(check["status"] == "ok" for check in checks.values()) else "failed"
    next_actions = _next_actions(
        checks,
        base_url=base_url,
        latest_commit_short=git_summary.get("latest_commit_short"),
    )
    return {
        "status": status,
        "repo_root": str(root),
        "checks": checks,
        "summary": {
            **git_summary,
            "deployment_base_url": base_url,
            "expected_deployed_commit": effective_expect_commit,
            "expected_actor_header_allowed": expect_actor_header_allowed,
            "next_actions": next_actions,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OpenJson release and deployment preflight checks.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--base-url", help="Optional deployment URL to smoke-test, for example https://openjson.thelumen.work.")
    parser.add_argument("--expect-commit", help="Expected deployed commit. Defaults to the local short commit when --base-url is set.")
    parser.add_argument(
        "--expect-actor-header-allowed",
        choices=("true", "false"),
        help="Expected /version runtime_config.actor_header_allowed value for the deployment smoke.",
    )
    args = parser.parse_args()

    expected_actor_header_allowed = None
    if args.expect_actor_header_allowed is not None:
        expected_actor_header_allowed = args.expect_actor_header_allowed == "true"

    report = build_release_preflight_report(
        args.repo_root,
        base_url=args.base_url,
        expect_commit=args.expect_commit,
        expect_actor_header_allowed=expected_actor_header_allowed,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
