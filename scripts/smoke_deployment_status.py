from __future__ import annotations

import argparse
import json
from typing import Any

import httpx


class DeploymentSmokeFailure(RuntimeError):
    pass


def _response_json(response: Any) -> dict[str, Any]:
    try:
        body = response.json()
    except Exception as exc:  # pragma: no cover - defensive for real HTTP failures
        raise DeploymentSmokeFailure(
            f"{response.request.method} {response.request.url} returned non-JSON: {response.text}"
        ) from exc
    if not isinstance(body, dict):
        raise DeploymentSmokeFailure(f"{response.request.method} {response.request.url} returned non-object JSON")
    return body


def _get(client: Any, path: str, *, expected_status: int = 200, **kwargs: Any) -> Any:
    response = client.get(path, **kwargs)
    if response.status_code != expected_status:
        raise DeploymentSmokeFailure(f"GET {path} -> {response.status_code}: {response.text}")
    return response


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentSmokeFailure(message)


def _json_or_text(response: Any) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            parsed = response.json()
        except Exception as exc:  # pragma: no cover - defensive for real HTTP failures
            return {
                "content_type": content_type,
                "json_error": str(exc),
                "text": response.text[:500],
            }
        return {
            "content_type": content_type,
            "json": parsed,
        }
    return {
        "content_type": content_type,
        "text": response.text[:500],
    }


def _probe_get(client: Any, path: str) -> dict[str, Any]:
    try:
        response = client.get(path)
    except Exception as exc:  # pragma: no cover - depends on external network failures
        return {
            "status": "failed",
            "path": path,
            "error": str(exc),
        }
    result = {
        "status": "ok" if response.status_code == 200 else "failed",
        "path": path,
        "http_status": response.status_code,
        "body": _json_or_text(response),
    }
    if response.status_code != 200:
        result["error"] = f"GET {path} returned HTTP {response.status_code}."
    return result


def _probe_body_json(probe: dict[str, Any]) -> Any:
    body = probe.get("body")
    if not isinstance(body, dict):
        return None
    return body.get("json")


def _add_failure(diagnostics: list[dict[str, Any]], *, code: str, message: str, details: dict[str, Any]) -> None:
    diagnostics.append(
        {
            "code": code,
            "message": message,
            "details": details,
        }
    )


def run_deployment_status_report(
    client: Any,
    *,
    expect_commit: str | None = None,
    expect_actor_header_allowed: bool | None = None,
    expect_backup_scheduler_enabled: bool | None = None,
    expect_backup_encryption_key_configured: bool | None = None,
) -> dict[str, Any]:
    checks = {
        "health": _probe_get(client, "/health"),
        "ready": _probe_get(client, "/ready"),
        "version": _probe_get(client, "/version"),
        "app": _probe_get(client, "/app"),
    }
    diagnostics: list[dict[str, Any]] = []

    health = _probe_body_json(checks["health"])
    if checks["health"]["status"] != "ok":
        _add_failure(
            diagnostics,
            code="HEALTH_ENDPOINT_FAILED",
            message="The deployment did not return HTTP 200 from /health.",
            details=checks["health"],
        )
    elif not isinstance(health, dict) or health.get("status") != "ok" or health.get("service") != "openjson-api":
        _add_failure(
            diagnostics,
            code="HEALTH_PAYLOAD_UNEXPECTED",
            message="The /health payload does not look like the OpenJson API.",
            details={"payload": health},
        )

    ready = _probe_body_json(checks["ready"])
    if checks["ready"]["status"] != "ok":
        _add_failure(
            diagnostics,
            code="READINESS_ENDPOINT_FAILED",
            message="The deployment did not return HTTP 200 from /ready.",
            details=checks["ready"],
        )
    elif not isinstance(ready, dict) or ready.get("status") != "ready":
        _add_failure(
            diagnostics,
            code="READINESS_PAYLOAD_UNEXPECTED",
            message="The /ready payload is not ready or does not look like the OpenJson readiness surface.",
            details={"payload": ready},
        )
    elif not isinstance(ready.get("database", {}).get("migrations"), dict):
        _add_failure(
            diagnostics,
            code="READINESS_MIGRATION_STATUS_MISSING",
            message=(
                "The /ready payload is missing migration status. The deployment is likely "
                "serving an older build; trigger a manual Render deploy from the latest main commit."
            ),
            details={"payload": ready},
        )
    elif ready.get("database", {}).get("migrations", {}).get("status") != "ok":
        _add_failure(
            diagnostics,
            code="READINESS_MIGRATION_STATUS_NOT_OK",
            message="The /ready migration status is not ok.",
            details={"payload": ready},
        )

    version = _probe_body_json(checks["version"])
    if checks["version"].get("http_status") == 404:
        _add_failure(
            diagnostics,
            code="VERSION_ENDPOINT_NOT_FOUND",
            message=(
                "The deployment is not serving a build that includes GET /version. "
                "Trigger a manual Render deploy from the latest main commit and verify "
                "Cloudflare points at the Render service."
            ),
            details=checks["version"],
        )
    elif checks["version"]["status"] != "ok":
        _add_failure(
            diagnostics,
            code="VERSION_ENDPOINT_FAILED",
            message="The deployment did not return HTTP 200 from /version.",
            details=checks["version"],
        )
    elif (
        not isinstance(version, dict)
        or version.get("service") != "openjson-api"
        or not isinstance(version.get("source"), dict)
        or not isinstance(version.get("runtime_config"), dict)
    ):
        _add_failure(
            diagnostics,
            code="VERSION_PAYLOAD_UNEXPECTED",
            message="The /version payload is missing required OpenJson deployment metadata.",
            details={"payload": version},
        )
    else:
        if expect_commit:
            actual_commit = version["source"].get("git_commit")
            if actual_commit != expect_commit and not (actual_commit or "").startswith(expect_commit):
                _add_failure(
                    diagnostics,
                    code="DEPLOYED_COMMIT_MISMATCH",
                    message="The deployed commit does not match the expected Git commit.",
                    details={"expected": expect_commit, "actual": actual_commit},
                )
        if expect_actor_header_allowed is not None:
            actual_allowed = version["runtime_config"].get("actor_header_allowed")
            if actual_allowed is not expect_actor_header_allowed:
                _add_failure(
                    diagnostics,
                    code="ACTOR_HEADER_CONFIG_MISMATCH",
                    message="The deployed actor-header fallback setting does not match the expected value.",
                    details={"expected": expect_actor_header_allowed, "actual": actual_allowed},
                )
        if expect_backup_scheduler_enabled is not None:
            actual_backup_scheduler_enabled = version["runtime_config"].get("backup_scheduler_enabled")
            if actual_backup_scheduler_enabled is not expect_backup_scheduler_enabled:
                _add_failure(
                    diagnostics,
                    code="BACKUP_SCHEDULER_CONFIG_MISMATCH",
                    message="The deployed backup scheduler setting does not match the expected value.",
                    details={
                        "expected": expect_backup_scheduler_enabled,
                        "actual": actual_backup_scheduler_enabled,
                    },
                )
        if expect_backup_encryption_key_configured is not None:
            actual_backup_encryption_key_configured = version["runtime_config"].get(
                "backup_encryption_key_configured"
            )
            if actual_backup_encryption_key_configured is not expect_backup_encryption_key_configured:
                _add_failure(
                    diagnostics,
                    code="BACKUP_ENCRYPTION_KEY_CONFIG_MISMATCH",
                    message="The deployed backup encryption key configured flag does not match the expected value.",
                    details={
                        "expected": expect_backup_encryption_key_configured,
                        "actual": actual_backup_encryption_key_configured,
                    },
                )

    app_body = checks["app"].get("body")
    app_text = app_body.get("text", "") if isinstance(app_body, dict) else ""
    app_content_type = app_body.get("content_type", "") if isinstance(app_body, dict) else ""
    if checks["app"]["status"] != "ok":
        _add_failure(
            diagnostics,
            code="APP_ENDPOINT_FAILED",
            message="The deployment did not return HTTP 200 from /app.",
            details=checks["app"],
        )
    elif "text/html" not in app_content_type or "OpenJson" not in app_text:
        _add_failure(
            diagnostics,
            code="APP_PAYLOAD_UNEXPECTED",
            message="The /app route did not return the expected OpenJson HTML shell.",
            details={"content_type": app_content_type, "contains_openjson": "OpenJson" in app_text},
        )

    return {
        "status": "ok" if not diagnostics else "failed",
        "checks": checks,
        "diagnostics": diagnostics,
    }


def run_deployment_status_smoke(
    client: Any,
    *,
    expect_commit: str | None = None,
    expect_actor_header_allowed: bool | None = None,
    expect_backup_scheduler_enabled: bool | None = None,
    expect_backup_encryption_key_configured: bool | None = None,
) -> dict[str, Any]:
    health = _response_json(_get(client, "/health"))
    ready = _response_json(_get(client, "/ready"))
    version = _response_json(_get(client, "/version"))
    app = _get(client, "/app")

    _require(health.get("status") == "ok", f"Unexpected health payload: {health}")
    _require(health.get("service") == "openjson-api", f"Unexpected health service: {health}")
    _require(ready.get("status") == "ready", f"Unexpected readiness payload: {ready}")
    _require(
        ready.get("database", {}).get("migrations", {}).get("status") == "ok",
        f"Readiness migration ledger is not ok: {ready}",
    )
    _require(version.get("service") == "openjson-api", f"Unexpected version service: {version}")
    _require("source" in version and isinstance(version["source"], dict), "Version payload missing source block.")
    _require(
        "runtime_config" in version and isinstance(version["runtime_config"], dict),
        "Version payload missing runtime_config block.",
    )
    _require("text/html" in app.headers.get("content-type", ""), "App route did not return HTML.")
    _require("OpenJson" in app.text, "App HTML does not contain OpenJson marker.")

    if expect_commit:
        actual_commit = version["source"].get("git_commit")
        _require(
            actual_commit == expect_commit or (actual_commit or "").startswith(expect_commit),
            f"Expected deployed commit {expect_commit}, got {actual_commit!r}",
        )

    if expect_actor_header_allowed is not None:
        actual_allowed = version["runtime_config"].get("actor_header_allowed")
        _require(
            actual_allowed is expect_actor_header_allowed,
            f"Expected actor_header_allowed={expect_actor_header_allowed}, got {actual_allowed!r}",
        )

    if expect_backup_scheduler_enabled is not None:
        actual_backup_scheduler_enabled = version["runtime_config"].get("backup_scheduler_enabled")
        _require(
            actual_backup_scheduler_enabled is expect_backup_scheduler_enabled,
            (
                f"Expected backup_scheduler_enabled={expect_backup_scheduler_enabled}, "
                f"got {actual_backup_scheduler_enabled!r}"
            ),
        )

    if expect_backup_encryption_key_configured is not None:
        actual_backup_encryption_key_configured = version["runtime_config"].get(
            "backup_encryption_key_configured"
        )
        _require(
            actual_backup_encryption_key_configured is expect_backup_encryption_key_configured,
            (
                f"Expected backup_encryption_key_configured={expect_backup_encryption_key_configured}, "
                f"got {actual_backup_encryption_key_configured!r}"
            ),
        )

    return {
        "status": "ok",
        "health": health,
        "ready": ready,
        "version": version,
        "app": {
            "content_type": app.headers.get("content-type"),
            "contains_openjson": "OpenJson" in app.text,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test an OpenJson deployment status surface.")
    parser.add_argument("--base-url", default="https://openjson.thelumen.work")
    parser.add_argument("--expect-commit")
    parser.add_argument(
        "--expect-actor-header-allowed",
        choices=("true", "false"),
        help="Expected /version runtime_config.actor_header_allowed value.",
    )
    parser.add_argument(
        "--expect-backup-scheduler-enabled",
        choices=("true", "false"),
        help="Expected /version runtime_config.backup_scheduler_enabled value.",
    )
    parser.add_argument(
        "--expect-backup-encryption-key-configured",
        choices=("true", "false"),
        help="Expected /version runtime_config.backup_encryption_key_configured value.",
    )
    args = parser.parse_args()

    expected_actor_header_allowed = None
    if args.expect_actor_header_allowed is not None:
        expected_actor_header_allowed = args.expect_actor_header_allowed == "true"
    expected_backup_scheduler_enabled = None
    if args.expect_backup_scheduler_enabled is not None:
        expected_backup_scheduler_enabled = args.expect_backup_scheduler_enabled == "true"
    expected_backup_encryption_key_configured = None
    if args.expect_backup_encryption_key_configured is not None:
        expected_backup_encryption_key_configured = args.expect_backup_encryption_key_configured == "true"

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=20.0, follow_redirects=True) as client:
        result = run_deployment_status_report(
            client,
            expect_commit=args.expect_commit,
            expect_actor_header_allowed=expected_actor_header_allowed,
            expect_backup_scheduler_enabled=expected_backup_scheduler_enabled,
            expect_backup_encryption_key_configured=expected_backup_encryption_key_configured,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
