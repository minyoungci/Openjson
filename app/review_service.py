from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.database import connect, utc_now
from app.document_service import apply_document_patch_in_transaction, validate_document_patch_candidate
from app.errors import AppError, ErrorCode
from app.permissions import ProjectPermission, require_actor, require_project_permission


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AppError(
            ErrorCode.INVALID_JSON_SYNTAX,
            "Value is not valid JSON.",
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


def _safe_load_change_field(row: sqlite3.Row, field: str) -> tuple[Any, dict[str, Any] | None]:
    try:
        return _json_loads(row[field]), None
    except json.JSONDecodeError as exc:
        return None, _json_decode_details(field, exc)


def _review_change_json_error_details(
    row: sqlite3.Row,
    failure: dict[str, Any],
) -> dict[str, Any]:
    return {
        "diagnostic_code": "REVIEW_CHANGE_JSON_DECODE_FAILED",
        "review_request_id": row["review_request_id"],
        "review_change_id": row["id"],
        "document_id": row["document_id"],
        **failure,
    }


def _load_change_field_for_apply(row: sqlite3.Row, field: str) -> Any:
    value, failure = _safe_load_change_field(row, field)
    if failure:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Stored review change JSON field is malformed.",
            _review_change_json_error_details(row, failure),
        )
    return value


def _ensure_text(value: str | None, field: str) -> str:
    if value is None or not value.strip():
        raise AppError(
            ErrorCode.INVALID_REVIEW_STATE,
            f"Review {field} is required.",
            {"field": field},
        )
    return value.strip()


def _review_row(conn: sqlite3.Connection, review_request_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM review_requests WHERE id = ?", (review_request_id,)).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.REVIEW_REQUEST_NOT_FOUND,
            "Review request not found.",
            {"review_request_id": review_request_id},
        )
    return row


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


def _change_rows(conn: sqlite3.Connection, review_request_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT *
            FROM review_request_changes
            WHERE review_request_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (review_request_id,),
        ).fetchall()
    )


def _decision_rows(conn: sqlite3.Connection, review_request_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT *
            FROM review_decisions
            WHERE review_request_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (review_request_id,),
        ).fetchall()
    )


def _ensure_review_not_terminal(row: sqlite3.Row, action: str) -> None:
    if row["status"] in {"applied", "closed"}:
        raise AppError(
            ErrorCode.INVALID_REVIEW_STATE,
            f"Review request cannot be {action} after it is {row['status']}.",
            {"status": row["status"]},
        )


def _row_to_change(row: sqlite3.Row) -> dict[str, Any]:
    change = {
        "id": row["id"],
        "review_request_id": row["review_request_id"],
        "document_id": row["document_id"],
        "base_version": row["base_version"],
        "reason": row["reason"],
        "created_at": row["created_at"],
    }
    json_errors = []
    for field in ("patch", "changed_paths"):
        change[field], failure = _safe_load_change_field(row, field)
        if failure:
            json_errors.append(failure)
    if json_errors:
        change["json_errors"] = json_errors
    return change


def _row_to_decision(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "review_request_id": row["review_request_id"],
        "actor_id": row["actor_id"],
        "decision_type": row["decision_type"],
        "body": row["body"],
        "created_at": row["created_at"],
    }


def _row_to_review(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "author_id": row["author_id"],
        "status": row["status"],
        "title": row["title"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "applied_by": row["applied_by"],
        "applied_at": row["applied_at"],
        "changes": [_row_to_change(change) for change in _change_rows(conn, row["id"])],
        "decisions": [_row_to_decision(decision) for decision in _decision_rows(conn, row["id"])],
    }


def _insert_decision(
    conn: sqlite3.Connection,
    *,
    review_request_id: str,
    actor_id: str,
    decision_type: str,
    body: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO review_decisions (
            id,
            review_request_id,
            actor_id,
            decision_type,
            body,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (_new_id("decision"), review_request_id, actor_id, decision_type, body, utc_now()),
    )


def create_review_request(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    title: str,
    description: str | None,
    changes: list[dict[str, Any]],
) -> dict[str, Any]:
    title = _ensure_text(title, "title")
    if not changes:
        raise AppError(
            ErrorCode.INVALID_REVIEW_STATE,
            "Review request requires at least one proposed change.",
        )
    document_ids = [change["document_id"] for change in changes]
    if len(document_ids) != len(set(document_ids)):
        raise AppError(
            ErrorCode.INVALID_REVIEW_STATE,
            "Review request can include only one proposed change per document in TASK_005.",
            {"document_ids": document_ids},
        )
    review_request_id = _new_id("review")
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.REVIEW_CREATE,
        )
        for change in changes:
            document = _active_document_row(conn, change["document_id"])
            if document["project_id"] != project_id:
                raise AppError(
                    ErrorCode.PERMISSION_DENIED,
                    "Review change document belongs to a different project.",
                    {"document_id": change["document_id"], "document_project_id": document["project_id"], "project_id": project_id},
                )
            validate_result = validate_document_patch_candidate(
                conn,
                row=document,
                base_version=change["base_version"],
                patch=change["patch"],
            )
            change["changed_paths"] = validate_result["changed_paths"]

        conn.execute(
            """
            INSERT INTO review_requests (
                id,
                project_id,
                author_id,
                status,
                title,
                description,
                created_at,
                updated_at,
                applied_by,
                applied_at
            )
            VALUES (?, ?, ?, 'open', ?, ?, ?, ?, NULL, NULL)
            """,
            (review_request_id, project_id, actor_id, title, description, now, now),
        )
        for change in changes:
            conn.execute(
                """
                INSERT INTO review_request_changes (
                    id,
                    review_request_id,
                    document_id,
                    base_version,
                    patch,
                    changed_paths,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id("review_change"),
                    review_request_id,
                    change["document_id"],
                    change["base_version"],
                    _json_dumps(change["patch"]),
                    _json_dumps(change["changed_paths"]),
                    change.get("reason"),
                    now,
                ),
            )
        return _row_to_review(conn, _review_row(conn, review_request_id))


def list_project_review_requests(
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
            permission=ProjectPermission.REVIEW_READ,
        )
        rows = conn.execute(
            """
            SELECT *
            FROM review_requests
            WHERE project_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        return {"project_id": project_id, "review_requests": [_row_to_review(conn, row) for row in rows]}


def get_review_request(
    db_path: str,
    *,
    review_request_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_actor(conn, actor_id)
        row = _review_row(conn, review_request_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=ProjectPermission.REVIEW_READ,
        )
        return _row_to_review(conn, row)


def approve_review_request(
    db_path: str,
    *,
    review_request_id: str,
    actor_id: str | None,
    comment: str | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        row = _review_row(conn, review_request_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=ProjectPermission.REVIEW_DECIDE,
        )
        _ensure_review_not_terminal(row, "approved")
        if row["author_id"] == actor_id:
            raise AppError(
                ErrorCode.INVALID_REVIEW_STATE,
                "Review authors cannot approve their own review request.",
                {"review_request_id": review_request_id, "actor_id": actor_id},
            )
        if row["status"] not in {"open", "changes_requested"}:
            raise AppError(
                ErrorCode.INVALID_REVIEW_STATE,
                "Review request cannot be approved from its current status.",
                {"status": row["status"]},
            )
        now = utc_now()
        _insert_decision(conn, review_request_id=review_request_id, actor_id=actor_id, decision_type="approve", body=comment)
        conn.execute(
            "UPDATE review_requests SET status = 'approved', updated_at = ? WHERE id = ?",
            (now, review_request_id),
        )
        return _row_to_review(conn, _review_row(conn, review_request_id))


def request_review_changes(
    db_path: str,
    *,
    review_request_id: str,
    actor_id: str | None,
    comment: str | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        row = _review_row(conn, review_request_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=ProjectPermission.REVIEW_DECIDE,
        )
        _ensure_review_not_terminal(row, "changed")
        if row["status"] not in {"open", "approved"}:
            raise AppError(
                ErrorCode.INVALID_REVIEW_STATE,
                "Review request cannot request changes from its current status.",
                {"status": row["status"]},
            )
        now = utc_now()
        _insert_decision(
            conn,
            review_request_id=review_request_id,
            actor_id=actor_id,
            decision_type="request_changes",
            body=comment,
        )
        conn.execute(
            "UPDATE review_requests SET status = 'changes_requested', updated_at = ? WHERE id = ?",
            (now, review_request_id),
        )
        return _row_to_review(conn, _review_row(conn, review_request_id))


def comment_on_review_request(
    db_path: str,
    *,
    review_request_id: str,
    actor_id: str | None,
    comment: str,
) -> dict[str, Any]:
    comment = _ensure_text(comment, "comment")
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        row = _review_row(conn, review_request_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=ProjectPermission.REVIEW_DECIDE,
        )
        _ensure_review_not_terminal(row, "commented on")
        now = utc_now()
        _insert_decision(conn, review_request_id=review_request_id, actor_id=actor_id, decision_type="comment", body=comment)
        conn.execute("UPDATE review_requests SET updated_at = ? WHERE id = ?", (now, review_request_id))
        return _row_to_review(conn, _review_row(conn, review_request_id))


def apply_review_request(
    db_path: str,
    *,
    review_request_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        row = _review_row(conn, review_request_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=ProjectPermission.REVIEW_APPLY,
        )
        if row["status"] != "approved":
            raise AppError(
                ErrorCode.INVALID_REVIEW_STATE,
                "Review request must be approved before apply.",
                {"status": row["status"]},
            )
        applied_documents = []
        for change in _change_rows(conn, review_request_id):
            document = _active_document_row(conn, change["document_id"])
            if document["project_id"] != row["project_id"]:
                raise AppError(
                    ErrorCode.PERMISSION_DENIED,
                    "Review change document belongs to a different project.",
                    {
                        "document_id": change["document_id"],
                        "document_project_id": document["project_id"],
                        "review_project_id": row["project_id"],
                    },
                )
            require_project_permission(
                conn,
                actor_id=actor_id,
                project_id=document["project_id"],
                permission=ProjectPermission.DOCUMENT_WRITE,
            )
            applied = apply_document_patch_in_transaction(
                conn,
                actor_id=actor_id,
                row=document,
                base_version=change["base_version"],
                patch=_load_change_field_for_apply(change, "patch"),
                reason=change["reason"],
            )
            applied_documents.append(
                {
                    "document_id": change["document_id"],
                    "previous_version": applied["previous_version"],
                    "current_version": applied["current_version"],
                    "changed_paths": applied["changed_paths"],
                }
            )
        now = utc_now()
        conn.execute(
            """
            UPDATE review_requests
            SET status = 'applied',
                updated_at = ?,
                applied_by = ?,
                applied_at = ?
            WHERE id = ?
            """,
            (now, actor_id, now, review_request_id),
        )
        response = _row_to_review(conn, _review_row(conn, review_request_id))
        response["applied_documents"] = applied_documents
        return response
