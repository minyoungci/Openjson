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


def run_deployment_status_smoke(
    client: Any,
    *,
    expect_commit: str | None = None,
    expect_actor_header_allowed: bool | None = None,
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
    args = parser.parse_args()

    expected_actor_header_allowed = None
    if args.expect_actor_header_allowed is not None:
        expected_actor_header_allowed = args.expect_actor_header_allowed == "true"

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=20.0, follow_redirects=True) as client:
        result = run_deployment_status_smoke(
            client,
            expect_commit=args.expect_commit,
            expect_actor_header_allowed=expected_actor_header_allowed,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
