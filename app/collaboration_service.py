from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import connect, utc_now
from app.errors import AppError, ErrorCode
from app.json_pointer import JsonPointerError, parse_pointer
from app.permissions import ProjectPermission, require_project_permission


ACTIVE_PRESENCE_SECONDS = 30
VALID_PRESENCE_STATUSES = {"viewing", "editing"}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _active_document_row(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT *
        FROM json_documents
        WHERE id = ? AND deleted_at IS NULL
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.DOCUMENT_NOT_FOUND,
            "Document not found.",
            {"document_id": document_id},
        )
    return row


def _ensure_cursor_path(cursor_path: str | None) -> str | None:
    if cursor_path is None or cursor_path == "":
        return None
    try:
        parse_pointer(cursor_path)
    except JsonPointerError as exc:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "cursor_path must be a valid JSON Pointer.",
            {"cursor_path": cursor_path, "message": str(exc)},
        ) from exc
    return cursor_path


def upsert_editor_presence(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
    status: str,
    base_version: int,
    dirty: bool,
    cursor_path: str | None = None,
) -> dict[str, Any]:
    if status not in VALID_PRESENCE_STATUSES:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Invalid editor presence status.",
            {"status": status, "allowed": sorted(VALID_PRESENCE_STATUSES)},
        )
    cursor_path = _ensure_cursor_path(cursor_path)
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _active_document_row(conn, document_id)
        permission = ProjectPermission.DOCUMENT_WRITE if status == "editing" else ProjectPermission.DOCUMENT_READ
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=permission,
        )
        if base_version < 0 or base_version > row["current_version"]:
            raise AppError(
                ErrorCode.INVALID_VERSION_RANGE,
                "base_version must refer to an existing document version.",
                {
                    "base_version": base_version,
                    "current_version": row["current_version"],
                    "document_id": document_id,
                },
            )
        now = utc_now()
        presence_id = _new_id("presence")
        conn.execute(
            """
            INSERT INTO editor_presence (
                id,
                document_id,
                actor_id,
                status,
                base_version,
                dirty,
                cursor_path,
                opened_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id, actor_id) DO UPDATE SET
                status = excluded.status,
                base_version = excluded.base_version,
                dirty = excluded.dirty,
                cursor_path = excluded.cursor_path,
                last_seen_at = excluded.last_seen_at
            """,
            (
                presence_id,
                document_id,
                actor_id,
                status,
                base_version,
                1 if dirty else 0,
                cursor_path,
                now,
                now,
            ),
        )
        return get_collaboration_state_in_connection(
            conn,
            row=row,
            actor_id=actor_id,
            since_version=base_version,
        )


def leave_editor_presence(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _active_document_row(conn, document_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=ProjectPermission.DOCUMENT_READ,
        )
        conn.execute(
            """
            DELETE FROM editor_presence
            WHERE document_id = ? AND actor_id = ?
            """,
            (document_id, actor_id),
        )
        return get_collaboration_state_in_connection(
            conn,
            row=row,
            actor_id=actor_id,
            since_version=None,
        )


def get_collaboration_state(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
    since_version: int | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = _active_document_row(conn, document_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=ProjectPermission.DOCUMENT_READ,
        )
        return get_collaboration_state_in_connection(
            conn,
            row=row,
            actor_id=actor_id,
            since_version=since_version,
        )


def get_collaboration_state_in_connection(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    actor_id: str | None,
    since_version: int | None,
) -> dict[str, Any]:
    if since_version is not None and since_version < 0:
        raise AppError(
            ErrorCode.INVALID_VERSION_RANGE,
            "since_version must be zero or a positive document version.",
            {"since_version": since_version},
        )
    active_users = _active_presence_rows(conn, row)
    checkpoints = _checkpoint_rows(conn, row["id"], since_version=since_version)
    current_version = row["current_version"]
    return {
        "document_id": row["id"],
        "project_id": row["project_id"],
        "full_path": row["full_path"],
        "current_version": current_version,
        "since_version": since_version,
        "has_updates": bool(since_version is not None and current_version > since_version),
        "server_time": utc_now(),
        "presence_timeout_seconds": ACTIVE_PRESENCE_SECONDS,
        "active_users": active_users,
        "checkpoints": checkpoints,
        "actor_id": actor_id,
    }


def _active_presence_rows(conn: sqlite3.Connection, row: sqlite3.Row) -> list[dict[str, Any]]:
    cutoff = _presence_cutoff()
    rows = conn.execute(
        """
        SELECT p.*, u.display_name
        FROM editor_presence AS p
        JOIN users AS u ON u.id = p.actor_id
        WHERE p.document_id = ?
          AND p.last_seen_at >= ?
        ORDER BY p.last_seen_at DESC, p.actor_id ASC
        """,
        (row["id"], cutoff),
    ).fetchall()
    return [
        {
            "actor_id": item["actor_id"],
            "display_name": item["display_name"],
            "status": item["status"],
            "base_version": item["base_version"],
            "dirty": bool(item["dirty"]),
            "cursor_path": item["cursor_path"],
            "last_seen_at": item["last_seen_at"],
            "opened_at": item["opened_at"],
            "is_stale_base": item["base_version"] < row["current_version"],
        }
        for item in rows
    ]


def _checkpoint_rows(
    conn: sqlite3.Connection,
    document_id: str,
    *,
    since_version: int | None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    params: list[Any] = [document_id]
    where = "e.document_id = ?"
    if since_version is not None:
        where += " AND e.result_version > ?"
        params.append(since_version)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT e.id,
               e.document_id,
               e.actor_id,
               u.display_name,
               e.event_type,
               e.validation_schema_id,
               e.base_version,
               e.result_version,
               e.changed_paths,
               e.summary,
               e.reason,
               e.created_at
        FROM document_events AS e
        JOIN users AS u ON u.id = e.actor_id
        WHERE {where}
        ORDER BY e.result_version DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    checkpoints = []
    for item in rows:
        checkpoints.append(
            {
                "event_id": item["id"],
                "document_id": item["document_id"],
                "actor_id": item["actor_id"],
                "display_name": item["display_name"],
                "event_type": item["event_type"],
                "validation_schema_id": item["validation_schema_id"],
                "base_version": item["base_version"],
                "result_version": item["result_version"],
                "changed_paths": _load_changed_paths(item),
                "summary": item["summary"],
                "reason": item["reason"],
                "created_at": item["created_at"],
            }
        )
    return checkpoints


def _load_changed_paths(row: sqlite3.Row) -> list[str]:
    try:
        value = json.loads(row["changed_paths"])
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _presence_cutoff() -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ACTIVE_PRESENCE_SECONDS)
    return cutoff.isoformat().replace("+00:00", "Z")
