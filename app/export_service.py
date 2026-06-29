from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.database import connect, utc_now
from app.integrity_service import (
    build_document_event_chain_report_from_event_rows,
    build_document_replay_report_from_event_rows,
)
from app.permissions import ProjectPermission, require_project_permission
from app.schema_service import safe_load_schema_json


FORMAT_VERSION = "openjson.project_export.v1"


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


def _row_to_workspace(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "owner_id": row["owner_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_project(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_member(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "user_id": row["user_id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


def _row_to_schema(row: sqlite3.Row) -> dict[str, Any]:
    schema_json, schema_error = safe_load_schema_json(row)
    schema = {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "version": row["version"],
        "schema": schema_json,
        "file_pattern": row["file_pattern"],
        "is_active": bool(row["is_active"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }
    if schema_error:
        schema["schema_json_error"] = schema_error
    return schema


def _row_to_document_event(row: sqlite3.Row) -> dict[str, Any]:
    event = {
        "id": row["id"],
        "document_id": row["document_id"],
        "actor_id": row["actor_id"],
        "validation_schema_id": row["validation_schema_id"],
        "event_type": row["event_type"],
        "base_version": row["base_version"],
        "result_version": row["result_version"],
        "summary": row["summary"],
        "reason": row["reason"],
        "created_at": row["created_at"],
    }
    json_errors = []
    for field in ("patch", "inverse_patch", "changed_paths", "before_values", "after_values"):
        event[field], error = _safe_json_loads(row[field], field)
        if error:
            json_errors.append(error)
    if json_errors:
        event["json_errors"] = json_errors
    return event


def _row_to_document(row: sqlite3.Row, events: list[dict[str, Any]]) -> dict[str, Any]:
    content, content_error = _safe_json_loads(row["current_snapshot_json"], "current_snapshot_json")
    document = {
        "id": row["id"],
        "project_id": row["project_id"],
        "full_path": row["full_path"],
        "current_version": row["current_version"],
        "schema_id": row["schema_id"],
        "content": content,
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted_at": row["deleted_at"],
        "events": events,
    }
    if content_error:
        document["content_error"] = content_error
    return document


def _row_to_comment(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "author_id": row["author_id"],
        "body": row["body"],
        "created_at": row["created_at"],
    }


def _comments_for_thread(conn: sqlite3.Connection, thread_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM comments
        WHERE thread_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (thread_id,),
    ).fetchall()
    return [_row_to_comment(row) for row in rows]


def _row_to_comment_thread(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    return {
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


def _row_to_review_change(row: sqlite3.Row) -> dict[str, Any]:
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
        change[field], error = _safe_json_loads(row[field], field)
        if error:
            json_errors.append(error)
    if json_errors:
        change["json_errors"] = json_errors
    return change


def _row_to_review_decision(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "review_request_id": row["review_request_id"],
        "actor_id": row["actor_id"],
        "decision_type": row["decision_type"],
        "body": row["body"],
        "created_at": row["created_at"],
    }


def _review_changes(conn: sqlite3.Connection, review_request_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM review_request_changes
        WHERE review_request_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (review_request_id,),
    ).fetchall()
    return [_row_to_review_change(row) for row in rows]


def _review_decisions(conn: sqlite3.Connection, review_request_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM review_decisions
        WHERE review_request_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (review_request_id,),
    ).fetchall()
    return [_row_to_review_decision(row) for row in rows]


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
        "changes": _review_changes(conn, row["id"]),
        "decisions": _review_decisions(conn, row["id"]),
    }


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


def _project_members(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            pm.id,
            pm.project_id,
            pm.user_id,
            pm.role,
            pm.created_at,
            u.email,
            u.display_name
        FROM project_members AS pm
        JOIN users AS u ON u.id = pm.user_id
        WHERE pm.project_id = ?
        ORDER BY pm.role ASC, u.email ASC, pm.id ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row_to_member(row) for row in rows]


def _project_schemas(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM schemas
        WHERE project_id = ?
        ORDER BY name ASC, version ASC, created_at ASC, id ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row_to_schema(row) for row in rows]


def _document_event_rows(conn: sqlite3.Connection, document_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM document_events
        WHERE document_id = ?
        ORDER BY result_version ASC, id ASC
        """,
        (document_id,),
    ).fetchall()


def _project_documents(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    include_deleted: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    where = ["project_id = ?"]
    if not include_deleted:
        where.append("deleted_at IS NULL")
    rows = conn.execute(
        f"""
        SELECT *
        FROM json_documents
        WHERE {" AND ".join(where)}
        ORDER BY full_path ASC, id ASC
        """,
        (project_id,),
    ).fetchall()
    documents = []
    replay_integrity_documents = []
    event_chain_integrity_documents = []
    for row in rows:
        event_rows = _document_event_rows(conn, row["id"])
        events = [_row_to_document_event(event_row) for event_row in event_rows]
        replay_report = build_document_replay_report_from_event_rows(row, event_rows)
        event_chain_report = build_document_event_chain_report_from_event_rows(row, event_rows)
        documents.append(_row_to_document(row, events))
        replay_summary = {
            "document_id": row["id"],
            "full_path": row["full_path"],
            "current_version": row["current_version"],
            "event_count": len(event_rows),
            "replay_matches_latest": replay_report["replay_matches_latest"],
            "event_chain_status": event_chain_report["status"],
            "event_chain_failure_count": event_chain_report["failure_count"],
        }
        if replay_report["status"] != "ok":
            replay_summary["error_code"] = replay_report.get("error_code")
            replay_summary["message"] = replay_report.get("message")
            replay_summary["details"] = replay_report.get("details", {})
        replay_integrity_documents.append(replay_summary)
        event_chain_integrity_documents.append(event_chain_report)
    return documents, replay_integrity_documents, event_chain_integrity_documents


def _project_comments(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    include_deleted: bool,
) -> list[dict[str, Any]]:
    deleted_filter = "" if include_deleted else "AND d.deleted_at IS NULL"
    rows = conn.execute(
        f"""
        SELECT ct.*
        FROM comment_threads AS ct
        JOIN json_documents AS d ON d.id = ct.document_id
        WHERE ct.project_id = ?
          {deleted_filter}
        ORDER BY ct.created_at ASC, ct.id ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row_to_comment_thread(conn, row) for row in rows]


def _project_reviews(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM review_requests
        WHERE project_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row_to_review(conn, row) for row in rows]


def _project_audit_log(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM audit_log
        WHERE project_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (project_id,),
    ).fetchall()
    return [_row_to_audit_event(row) for row in rows]


def export_project_archive(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    include_deleted: bool = False,
    include_comments: bool = False,
    include_reviews: bool = False,
    include_audit_log: bool = False,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.EXPORT_READ,
        )
        project_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        workspace_row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (project_row["workspace_id"],)).fetchone()
        documents, replay_integrity_documents, event_chain_integrity_documents = _project_documents(
            conn,
            project_id,
            include_deleted=include_deleted,
        )
        document_event_count = sum(item["event_count"] for item in replay_integrity_documents)
        replay_consistent = all(item["replay_matches_latest"] for item in replay_integrity_documents)
        replay_failures = [
            item for item in replay_integrity_documents if not item["replay_matches_latest"]
        ]
        event_chain_failures = [
            report for report in event_chain_integrity_documents if report["status"] != "ok"
        ]
        event_chain_consistent = not event_chain_failures
        replay_status = "ok" if replay_consistent else "failed"
        event_chain_status = "ok" if event_chain_consistent else "failed"
        integrity_status = "ok" if replay_consistent and event_chain_consistent else "failed"
        return {
            "format_version": FORMAT_VERSION,
            "exported_at": utc_now(),
            "project": _row_to_project(project_row),
            "workspace": _row_to_workspace(workspace_row),
            "members": _project_members(conn, project_id),
            "options": {
                "include_deleted": include_deleted,
                "include_comments": include_comments,
                "include_reviews": include_reviews,
                "include_audit_log": include_audit_log,
            },
            "schemas": _project_schemas(conn, project_id),
            "documents": documents,
            "comments": _project_comments(conn, project_id, include_deleted=include_deleted) if include_comments else [],
            "reviews": _project_reviews(conn, project_id) if include_reviews else [],
            "audit_log": _project_audit_log(conn, project_id) if include_audit_log else [],
            "integrity": {
                "status": integrity_status,
                "replay_consistent": replay_consistent,
                "event_chain_consistent": event_chain_consistent,
                "document_count": len(documents),
                "document_event_count": document_event_count,
                "documents": replay_integrity_documents,
                "checks": {
                    "replay": {
                        "status": replay_status,
                        "checked_documents": len(replay_integrity_documents),
                        "failure_count": len(replay_failures),
                        "documents": replay_integrity_documents,
                        "failures": replay_failures,
                    },
                    "event_chain": {
                        "status": event_chain_status,
                        "checked_documents": len(event_chain_integrity_documents),
                        "failure_count": len(event_chain_failures),
                        "documents": event_chain_integrity_documents,
                        "failures": event_chain_failures,
                    },
                },
            },
        }
