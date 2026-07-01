from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.database import connect
from app.errors import AppError, ErrorCode
from app.permissions import ProjectPermission, require_project_permission


DEFAULT_MAX_PROJECT_DOCUMENTS = 10_000
DEFAULT_MAX_PROJECT_SNAPSHOT_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class ProjectUsageLimitConfig:
    enabled: bool
    max_documents: int
    max_snapshot_bytes: int


def project_usage_limit_config_from_env(
    *,
    enabled_raw: str | None = None,
    max_documents_raw: str | None = None,
    max_snapshot_bytes_raw: str | None = None,
) -> ProjectUsageLimitConfig:
    return ProjectUsageLimitConfig(
        enabled=_env_flag(_env_or_value("OPENJSON_PROJECT_USAGE_LIMIT_ENABLED", enabled_raw)),
        max_documents=_positive_int(
            _env_or_value("OPENJSON_MAX_PROJECT_DOCUMENTS", max_documents_raw),
            default=DEFAULT_MAX_PROJECT_DOCUMENTS,
        ),
        max_snapshot_bytes=_positive_int(
            _env_or_value("OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES", max_snapshot_bytes_raw),
            default=DEFAULT_MAX_PROJECT_SNAPSHOT_BYTES,
        ),
    )


def get_project_usage(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        return project_usage_response(conn, project_id=project_id)


def project_usage_response(conn: sqlite3.Connection, *, project_id: str) -> dict[str, Any]:
    usage = current_project_usage(conn, project_id=project_id)
    config = project_usage_limit_config_from_env()
    return {
        "project_id": project_id,
        "usage": usage,
        "limits": _limit_payload(config),
    }


def ensure_project_usage_allows_snapshot(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    candidate_snapshot: Any,
    replacing_document_id: str | None = None,
    document_count_delta: int = 0,
    config: ProjectUsageLimitConfig | None = None,
) -> None:
    config = config or project_usage_limit_config_from_env()
    if not config.enabled:
        return

    usage = current_project_usage(conn, project_id=project_id)
    current_document_bytes = 0
    if replacing_document_id is not None:
        row = conn.execute(
            """
            SELECT current_snapshot_json
            FROM json_documents
            WHERE id = ?
              AND project_id = ?
              AND deleted_at IS NULL
            """,
            (replacing_document_id, project_id),
        ).fetchone()
        if row is not None:
            current_document_bytes = _stored_json_bytes(row["current_snapshot_json"])

    candidate_bytes = canonical_snapshot_bytes(candidate_snapshot)
    attempted_usage = {
        "active_document_count": usage["active_document_count"] + document_count_delta,
        "active_snapshot_bytes": usage["active_snapshot_bytes"] - current_document_bytes + candidate_bytes,
    }

    violations = []
    if attempted_usage["active_document_count"] > config.max_documents:
        violations.append(
            {
                "limit": "max_project_documents",
                "max": config.max_documents,
                "attempted": attempted_usage["active_document_count"],
            }
        )
    if attempted_usage["active_snapshot_bytes"] > config.max_snapshot_bytes:
        violations.append(
            {
                "limit": "max_project_snapshot_bytes",
                "max": config.max_snapshot_bytes,
                "attempted": attempted_usage["active_snapshot_bytes"],
            }
        )
    if not violations:
        return

    raise AppError(
        ErrorCode.PROJECT_USAGE_LIMIT_EXCEEDED,
        "Project usage limit would be exceeded.",
        {
            "project_id": project_id,
            "usage": usage,
            "attempted_usage": attempted_usage,
            "limits": _limit_payload(config),
            "violations": violations,
        },
    )


def current_project_usage(conn: sqlite3.Connection, *, project_id: str) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS active_document_count,
               COALESCE(SUM(length(CAST(current_snapshot_json AS BLOB))), 0) AS active_snapshot_bytes
        FROM json_documents
        WHERE project_id = ?
          AND deleted_at IS NULL
        """,
        (project_id,),
    ).fetchone()
    return {
        "active_document_count": int(row["active_document_count"]),
        "active_snapshot_bytes": int(row["active_snapshot_bytes"]),
    }


def canonical_snapshot_bytes(value: Any) -> int:
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AppError(
            ErrorCode.INVALID_JSON_SYNTAX,
            "Value is not valid JSON.",
            {"message": str(exc)},
        ) from exc
    return _stored_json_bytes(rendered)


def _stored_json_bytes(value: str) -> int:
    return len(value.encode("utf-8"))


def _limit_payload(config: ProjectUsageLimitConfig) -> dict[str, int | bool]:
    return {
        "enabled": config.enabled,
        "max_project_documents": config.max_documents,
        "max_project_snapshot_bytes": config.max_snapshot_bytes,
    }


def _env_or_value(name: str, value: str | None) -> str | None:
    if value is not None:
        return value
    return os.environ.get(name)


def _env_flag(raw: str | None) -> bool:
    return bool(raw and raw.strip().lower() in {"1", "true", "yes", "on"})


def _positive_int(raw: str | None, *, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)
