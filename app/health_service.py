from __future__ import annotations

import os
from typing import Any

from app.database import connect, get_schema_migration_status
from app.errors import AppError, ErrorCode
from app.rate_limit import RateLimitConfig


REQUIRED_TABLES = {
    "schema_migrations",
    "users",
    "user_credentials",
    "user_sessions",
    "refresh_tokens",
    "api_tokens",
    "workspaces",
    "projects",
    "project_members",
    "project_invitations",
    "email_deliveries",
    "oidc_states",
    "oidc_identities",
    "offline_sync_operations",
    "json_documents",
    "document_events",
    "schemas",
    "comment_threads",
    "comments",
    "review_requests",
    "review_request_changes",
    "review_decisions",
    "audit_log",
}


def health_status() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "openjson-api",
    }


def version_status(
    *,
    allow_actor_header: bool,
    cors_origins_configured: bool,
    rate_limit_config: RateLimitConfig,
    websocket_rate_limit_config: RateLimitConfig,
) -> dict[str, Any]:
    return {
        "service": "openjson-api",
        "deployment": {
            "platform": _deployment_platform(),
            "service_name": _optional_env("RENDER_SERVICE_NAME"),
            "service_type": _optional_env("RENDER_SERVICE_TYPE"),
            "external_hostname": _optional_env("RENDER_EXTERNAL_HOSTNAME"),
        },
        "source": {
            "git_commit": _first_env("OPENJSON_GIT_COMMIT", "RENDER_GIT_COMMIT"),
            "git_branch": _first_env("OPENJSON_GIT_BRANCH", "RENDER_GIT_BRANCH"),
            "git_repo_slug": _first_env("OPENJSON_GIT_REPO_SLUG", "RENDER_GIT_REPO_SLUG"),
        },
        "runtime_config": {
            "actor_header_allowed": allow_actor_header,
            "cors_origins_configured": cors_origins_configured,
            "email_backend": _optional_env("OPENJSON_EMAIL_BACKEND") or "console",
            "rate_limit_enabled": rate_limit_config.enabled,
            "rate_limit_requests": rate_limit_config.requests,
            "rate_limit_window_seconds": rate_limit_config.window_seconds,
            "websocket_rate_limit_enabled": websocket_rate_limit_config.enabled,
            "websocket_rate_limit_messages": websocket_rate_limit_config.requests,
            "websocket_rate_limit_window_seconds": websocket_rate_limit_config.window_seconds,
            "redis_fanout_enabled": bool(_optional_env("OPENJSON_REDIS_URL")),
            "oidc_configured": all(
                _optional_env(name)
                for name in (
                    "OPENJSON_OIDC_ISSUER",
                    "OPENJSON_OIDC_CLIENT_ID",
                    "OPENJSON_OIDC_CLIENT_SECRET",
                    "OPENJSON_OIDC_REDIRECT_URI",
                )
            ),
            "storage_backend": "sqlite",
        },
    }


def readiness_status(db_path: str) -> dict[str, Any]:
    try:
        with connect(db_path) as conn:
            foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            tables = {
                row["name"]
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                ).fetchall()
            }
    except Exception as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Readiness check failed.",
            {"database": {"connected": False, "message": str(exc)}},
            status_code=503,
        ) from exc

    missing_tables = sorted(REQUIRED_TABLES - tables)
    if missing_tables or not foreign_keys:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Readiness check failed.",
            {
                "database": {
                    "connected": True,
                    "foreign_keys_enabled": foreign_keys,
                    "missing_tables": missing_tables,
                }
            },
            status_code=503,
        )

    migrations = get_schema_migration_status(db_path)
    if migrations["status"] != "ok":
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Readiness check failed.",
            {
                "database": {
                    "connected": True,
                    "foreign_keys_enabled": True,
                    "missing_tables": [],
                    "migrations": migrations,
                }
            },
            status_code=503,
        )

    return {
        "status": "ready",
        "database": {
            "connected": True,
            "foreign_keys_enabled": True,
            "required_tables": sorted(REQUIRED_TABLES),
            "migrations": migrations,
        },
    }


def _deployment_platform() -> str:
    if _optional_env("RENDER"):
        return "render"
    return _optional_env("OPENJSON_DEPLOYMENT_PLATFORM") or "local"


def _first_env(*names: str) -> str | None:
    for name in names:
        value = _optional_env(name)
        if value:
            return value
    return None


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
