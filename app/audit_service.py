from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.database import connect, utc_now
from app.errors import AppError, ErrorCode
from app.permissions import ProjectPermission, require_project_permission


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AppError(
            ErrorCode.INVALID_JSON_SYNTAX,
            "Audit details are not valid JSON.",
            {"message": str(exc)},
        ) from exc


def _json_loads(value: str) -> Any:
    return json.loads(value)


def _json_decode_details(field: str, error: json.JSONDecodeError) -> dict[str, Any]:
    return {
        "field": field,
        "message": error.msg,
        "line": error.lineno,
        "column": error.colno,
        "position": error.pos,
    }


def _safe_json_loads(value: str, field: str) -> tuple[Any, dict[str, Any] | None]:
    try:
        return _json_loads(value), None
    except json.JSONDecodeError as exc:
        return None, _json_decode_details(field, exc)


def record_audit_event(
    conn: sqlite3.Connection,
    *,
    actor_id: str | None,
    action: str,
    target_type: str,
    outcome: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    document_id: str | None = None,
    target_id: str | None = None,
    error_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    if outcome not in {"success", "failure"}:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Audit outcome is not supported.",
            {"outcome": outcome},
        )
    audit_id = _new_id("audit")
    conn.execute(
        """
        INSERT INTO audit_log (
            id,
            actor_id,
            workspace_id,
            project_id,
            document_id,
            action,
            target_type,
            target_id,
            outcome,
            error_code,
            details,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            actor_id,
            workspace_id,
            project_id,
            document_id,
            action,
            target_type,
            target_id,
            outcome,
            error_code,
            _json_dumps(details or {}),
            utc_now(),
        ),
    )
    return audit_id


def _row_to_audit_event(row: sqlite3.Row) -> dict[str, Any]:
    details, details_error = _safe_json_loads(row["details"], "details")
    event = {
        "id": row["id"],
        "actor_id": row["actor_id"],
        "workspace_id": row["workspace_id"],
        "project_id": row["project_id"],
        "document_id": row["document_id"],
        "action": row["action"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "outcome": row["outcome"],
        "error_code": row["error_code"],
        "details": details,
        "created_at": row["created_at"],
    }
    if details_error:
        event["details_error"] = details_error
    return event


def list_project_audit_log(
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
            permission=ProjectPermission.AUDIT_READ,
        )
        rows = conn.execute(
            """
            SELECT *
            FROM audit_log
            WHERE project_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        return {"project_id": project_id, "events": [_row_to_audit_event(row) for row in rows]}
