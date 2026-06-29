from __future__ import annotations

from typing import Any

from app.database import connect
from app.errors import AppError, ErrorCode


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

    return {
        "status": "ready",
        "database": {
            "connected": True,
            "foreign_keys_enabled": True,
            "required_tables": sorted(REQUIRED_TABLES),
        },
    }
