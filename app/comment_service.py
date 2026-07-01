from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from app.database import connect, utc_now
from app.errors import AppError, ErrorCode
from app.json_pointer import JsonPointerError, parse_pointer
from app.permissions import ProjectPermission, require_actor, require_project_permission


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _ensure_body(body: str) -> str:
    if body is None or not body.strip():
        raise AppError(
            ErrorCode.INVALID_COMMENT_ANCHOR,
            "Comment body is required.",
        )
    return body.strip()


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


def _document_row_including_deleted(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM json_documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.DOCUMENT_NOT_FOUND,
            "Document not found.",
            {"document_id": document_id},
        )
    return row


def _thread_row(conn: sqlite3.Connection, thread_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT t.*,
               creator.display_name AS created_by_display_name,
               resolver.display_name AS resolved_by_display_name
        FROM comment_threads AS t
        LEFT JOIN users AS creator ON creator.id = t.created_by
        LEFT JOIN users AS resolver ON resolver.id = t.resolved_by
        WHERE t.id = ?
        """,
        (thread_id,),
    ).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.COMMENT_THREAD_NOT_FOUND,
            "Comment thread not found.",
            {"thread_id": thread_id},
        )
    return row


def _validate_anchor(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    anchor_type: str,
    path: str | None,
    event_id: str | None,
) -> tuple[str | None, str | None]:
    if anchor_type == "document":
        if path is not None or event_id is not None:
            raise AppError(
                ErrorCode.INVALID_COMMENT_ANCHOR,
                "Document comments cannot include path or event anchors.",
                {"anchor_type": anchor_type},
            )
        return None, None
    if anchor_type == "path":
        if path is None:
            raise AppError(
                ErrorCode.INVALID_COMMENT_ANCHOR,
                "Path comment requires a JSON Pointer path.",
            )
        try:
            parse_pointer(path)
        except JsonPointerError as exc:
            raise AppError(
                ErrorCode.INVALID_COMMENT_ANCHOR,
                "Comment path must be a valid JSON Pointer.",
                {"path": path, "message": str(exc)},
            ) from exc
        if event_id is not None:
            raise AppError(
                ErrorCode.INVALID_COMMENT_ANCHOR,
                "Path comments cannot include an event anchor.",
            )
        return path, None
    if anchor_type == "event":
        if event_id is None:
            raise AppError(
                ErrorCode.INVALID_COMMENT_ANCHOR,
                "Event comment requires an event_id.",
            )
        if path is not None:
            raise AppError(
                ErrorCode.INVALID_COMMENT_ANCHOR,
                "Event comments cannot include a path anchor.",
            )
        event = conn.execute(
            "SELECT id FROM document_events WHERE id = ? AND document_id = ?",
            (event_id, document_id),
        ).fetchone()
        if event is None:
            raise AppError(
                ErrorCode.INVALID_COMMENT_ANCHOR,
                "Event anchor does not belong to this document.",
                {"document_id": document_id, "event_id": event_id},
            )
        return None, event_id
    raise AppError(
        ErrorCode.INVALID_COMMENT_ANCHOR,
        "Unsupported comment anchor_type.",
        {"anchor_type": anchor_type, "supported_anchor_types": ["document", "path", "event"]},
    )


def _row_to_comment(row: sqlite3.Row) -> dict[str, Any]:
    comment = {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "author_id": row["author_id"],
        "body": row["body"],
        "created_at": row["created_at"],
    }
    if "author_display_name" in row.keys():
        comment["author_display_name"] = row["author_display_name"]
    return comment


def _comments_for_thread(conn: sqlite3.Connection, thread_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.*, u.display_name AS author_display_name
        FROM comments AS c
        LEFT JOIN users AS u ON u.id = c.author_id
        WHERE c.thread_id = ?
        ORDER BY c.created_at ASC, c.id ASC
        """,
        (thread_id,),
    ).fetchall()
    return [_row_to_comment(row) for row in rows]


def _row_to_thread(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    thread = {
        "id": row["id"],
        "project_id": row["project_id"],
        "document_id": row["document_id"],
        "anchor_type": row["anchor_type"],
        "path": row["anchor_path"],
        "event_id": row["anchor_event_id"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "resolved_by": row["resolved_by"],
        "resolved_at": row["resolved_at"],
        "comments": _comments_for_thread(conn, row["id"]),
    }
    if "created_by_display_name" in row.keys():
        thread["created_by_display_name"] = row["created_by_display_name"]
    if "resolved_by_display_name" in row.keys():
        thread["resolved_by_display_name"] = row["resolved_by_display_name"]
    return thread


def create_comment_thread(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
    body: str,
    anchor_type: str = "document",
    path: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    body = _ensure_body(body)
    thread_id = _new_id("thread")
    comment_id = _new_id("comment")
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        document = _active_document_row(conn, document_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=document["project_id"],
            permission=ProjectPermission.COMMENT_WRITE,
        )
        anchor_path, anchor_event_id = _validate_anchor(
            conn,
            document_id=document_id,
            anchor_type=anchor_type,
            path=path,
            event_id=event_id,
        )
        conn.execute(
            """
            INSERT INTO comment_threads (
                id,
                project_id,
                document_id,
                anchor_type,
                anchor_path,
                anchor_event_id,
                status,
                created_by,
                created_at,
                updated_at,
                resolved_by,
                resolved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, NULL, NULL)
            """,
            (
                thread_id,
                document["project_id"],
                document_id,
                anchor_type,
                anchor_path,
                anchor_event_id,
                actor_id,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO comments (id, thread_id, author_id, body, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (comment_id, thread_id, actor_id, body, now),
        )
        return _row_to_thread(conn, _thread_row(conn, thread_id))


def list_comment_threads(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_actor(conn, actor_id)
        document = _document_row_including_deleted(conn, document_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=document["project_id"],
            permission=ProjectPermission.COMMENT_READ,
        )
        rows = conn.execute(
            """
            SELECT t.*,
                   creator.display_name AS created_by_display_name,
                   resolver.display_name AS resolved_by_display_name
            FROM comment_threads AS t
            LEFT JOIN users AS creator ON creator.id = t.created_by
            LEFT JOIN users AS resolver ON resolver.id = t.resolved_by
            WHERE t.document_id = ?
            ORDER BY t.created_at ASC, t.id ASC
            """,
            (document_id,),
        ).fetchall()
        return {"document_id": document_id, "threads": [_row_to_thread(conn, row) for row in rows]}


def add_comment(
    db_path: str,
    *,
    thread_id: str,
    actor_id: str | None,
    body: str,
) -> dict[str, Any]:
    body = _ensure_body(body)
    comment_id = _new_id("comment")
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        thread = _thread_row(conn, thread_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=thread["project_id"],
            permission=ProjectPermission.COMMENT_WRITE,
        )
        conn.execute(
            """
            INSERT INTO comments (id, thread_id, author_id, body, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (comment_id, thread_id, actor_id, body, now),
        )
        conn.execute("UPDATE comment_threads SET updated_at = ? WHERE id = ?", (now, thread_id))
        return _row_to_comment(
            conn.execute(
                """
                SELECT c.*, u.display_name AS author_display_name
                FROM comments AS c
                LEFT JOIN users AS u ON u.id = c.author_id
                WHERE c.id = ?
                """,
                (comment_id,),
            ).fetchone()
        )


def resolve_comment_thread(
    db_path: str,
    *,
    thread_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        thread = _thread_row(conn, thread_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=thread["project_id"],
            permission=ProjectPermission.COMMENT_WRITE,
        )
        conn.execute(
            """
            UPDATE comment_threads
            SET status = 'resolved',
                updated_at = ?,
                resolved_by = ?,
                resolved_at = ?
            WHERE id = ?
            """,
            (now, actor_id, now, thread_id),
        )
        return _row_to_thread(conn, _thread_row(conn, thread_id))


def reopen_comment_thread(
    db_path: str,
    *,
    thread_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        thread = _thread_row(conn, thread_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=thread["project_id"],
            permission=ProjectPermission.COMMENT_WRITE,
        )
        conn.execute(
            """
            UPDATE comment_threads
            SET status = 'open',
                updated_at = ?,
                resolved_by = NULL,
                resolved_at = NULL
            WHERE id = ?
            """,
            (now, thread_id),
        )
        return _row_to_thread(conn, _thread_row(conn, thread_id))
