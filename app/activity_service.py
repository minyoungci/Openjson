from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.database import connect
from app.errors import AppError, ErrorCode
from app.permissions import ProjectPermission, require_project_permission


ACTIVITY_SOURCES = {"all", "document_events", "audit_log"}


def _ensure_limit_offset(limit: int, offset: int) -> None:
    if limit < 1 or limit > 100:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "limit must be between 1 and 100.",
            {"limit": limit},
        )
    if offset < 0:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "offset must be greater than or equal to 0.",
            {"offset": offset},
        )


def _ensure_source(source: str | None) -> str:
    if source is None:
        return "all"
    normalized = source.strip()
    if normalized not in ACTIVITY_SOURCES:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "source must be one of all, document_events, or audit_log.",
            {"source": source, "allowed_sources": sorted(ACTIVITY_SOURCES)},
        )
    return normalized


def _ensure_non_blank_filter(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"{field} filter must not be empty.",
            {field: value},
        )
    return normalized


def _load_json(value: str) -> Any:
    return json.loads(value)


def _json_decode_details(field: str, error: json.JSONDecodeError) -> dict[str, Any]:
    return {
        "field": field,
        "message": error.msg,
        "line": error.lineno,
        "column": error.colno,
        "position": error.pos,
    }


def _safe_load_json(value: str, field: str) -> tuple[Any, dict[str, Any] | None]:
    try:
        return _load_json(value), None
    except json.JSONDecodeError as exc:
        return None, _json_decode_details(field, exc)


def _row_to_document_activity(row: sqlite3.Row) -> dict[str, Any]:
    changed_paths, changed_paths_error = _safe_load_json(row["changed_paths"], "changed_paths")
    document_event = {
        "event_type": row["event_type"],
        "base_version": row["base_version"],
        "result_version": row["result_version"],
        "validation_schema_id": row["validation_schema_id"],
        "changed_paths": changed_paths,
        "summary": row["summary"],
        "reason": row["reason"],
    }
    if changed_paths_error:
        document_event["json_errors"] = [changed_paths_error]
    return {
        "source": "document_event",
        "id": row["id"],
        "activity_type": f"document.{row['event_type']}",
        "actor_id": row["actor_id"],
        "document_id": row["document_id"],
        "full_path": row["full_path"],
        "outcome": "success",
        "created_at": row["created_at"],
        "document_event": document_event,
        "audit_log": None,
    }


def _row_to_audit_activity(row: sqlite3.Row) -> dict[str, Any]:
    details, details_error = _safe_load_json(row["details"], "details")
    audit_log = {
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "error_code": row["error_code"],
        "details": details,
    }
    if details_error:
        audit_log["details_error"] = details_error
    return {
        "source": "audit_log",
        "id": row["id"],
        "activity_type": row["action"],
        "actor_id": row["actor_id"],
        "document_id": row["document_id"],
        "full_path": row["full_path"],
        "outcome": row["outcome"],
        "created_at": row["created_at"],
        "document_event": None,
        "audit_log": audit_log,
    }


def _document_belongs_to_project(conn: sqlite3.Connection, *, document_id: str, project_id: str) -> None:
    row = conn.execute(
        """
        SELECT id
        FROM json_documents
        WHERE id = ? AND project_id = ?
        """,
        (document_id, project_id),
    ).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.DOCUMENT_NOT_FOUND,
            "Document not found in project.",
            {"document_id": document_id, "project_id": project_id},
        )


def get_project_activity(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    source: str | None = "all",
    activity_actor_id: str | None = None,
    document_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    _ensure_limit_offset(limit, offset)
    source = _ensure_source(source)
    activity_actor_id = _ensure_non_blank_filter(activity_actor_id, "actor_id")
    document_id = _ensure_non_blank_filter(document_id, "document_id")

    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.AUDIT_READ,
        )
        if document_id is not None:
            _document_belongs_to_project(conn, document_id=document_id, project_id=project_id)

        items: list[dict[str, Any]] = []
        if source in {"all", "document_events"}:
            where = ["d.project_id = ?"]
            params: list[Any] = [project_id]
            if activity_actor_id is not None:
                where.append("e.actor_id = ?")
                params.append(activity_actor_id)
            if document_id is not None:
                where.append("e.document_id = ?")
                params.append(document_id)
            rows = conn.execute(
                f"""
                SELECT e.*, d.full_path AS full_path
                FROM document_events AS e
                JOIN json_documents AS d ON d.id = e.document_id
                WHERE {" AND ".join(where)}
                """,
                params,
            ).fetchall()
            items.extend(_row_to_document_activity(row) for row in rows)

        if source in {"all", "audit_log"}:
            where = ["a.project_id = ?"]
            params = [project_id]
            if activity_actor_id is not None:
                where.append("a.actor_id = ?")
                params.append(activity_actor_id)
            if document_id is not None:
                where.append("a.document_id = ?")
                params.append(document_id)
            rows = conn.execute(
                f"""
                SELECT a.*, d.full_path AS full_path
                FROM audit_log AS a
                LEFT JOIN json_documents AS d ON d.id = a.document_id
                WHERE {" AND ".join(where)}
                """,
                params,
            ).fetchall()
            items.extend(_row_to_audit_activity(row) for row in rows)

    items.sort(key=lambda item: (item["created_at"], item["activity_type"], item["id"]), reverse=True)
    total = len(items)
    page = items[offset : offset + limit]
    return {
        "project_id": project_id,
        "items": page,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total": total,
            "has_more": offset + len(page) < total,
        },
        "filters": {
            "source": source,
            "actor_id": activity_actor_id,
            "document_id": document_id,
        },
    }
