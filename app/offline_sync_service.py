from __future__ import annotations

import json
from typing import Any

from app.database import connect, utc_now
from app.document_service import update_document_content
from app.errors import AppError, ErrorCode
from app.permissions import ProjectPermission, require_project_permission


MAX_OFFLINE_SYNC_ITEMS = 50


def apply_offline_sync_batch(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    if not actor_id:
        raise AppError(ErrorCode.AUTH_REQUIRED, "Offline sync requires actor information.")
    if not isinstance(items, list) or len(items) > MAX_OFFLINE_SYNC_ITEMS:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Offline sync batch size is invalid.",
            {"max_items": MAX_OFFLINE_SYNC_ITEMS},
        )
    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_WRITE,
        )
    results = [_apply_one(db_path, project_id=project_id, actor_id=actor_id, item=item) for item in items]
    return {
        "project_id": project_id,
        "actor_id": actor_id,
        "results": results,
        "summary": {
            "applied": sum(1 for item in results if item["status"] == "applied"),
            "conflict": sum(1 for item in results if item["status"] == "conflict"),
            "failed": sum(1 for item in results if item["status"] == "failed"),
        },
    }


def _apply_one(db_path: str, *, project_id: str, actor_id: str, item: dict[str, Any]) -> dict[str, Any]:
    client_operation_id = _required_text(item.get("client_operation_id"), "client_operation_id")
    existing = _existing_result(db_path, actor_id=actor_id, client_operation_id=client_operation_id)
    if existing is not None:
        return existing
    document_id = _required_text(item.get("document_id"), "document_id")
    operation_type = item.get("operation_type") or "content_update"
    if operation_type != "content_update":
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Offline sync operation_type is not supported.",
            {"operation_type": operation_type, "allowed": ["content_update"]},
        )
    base_version = item.get("base_version")
    if not isinstance(base_version, int):
        raise AppError(ErrorCode.INVALID_REQUEST, "base_version must be an integer.")
    request_json = {
        "document_id": document_id,
        "operation_type": operation_type,
        "base_version": base_version,
        "merge_strategy": item.get("merge_strategy") or "reject",
        "reason": item.get("reason") or "Offline sync content update",
    }
    content_provided = "content" in item
    content_text_provided = "content_text" in item
    if content_provided:
        request_json["content"] = item.get("content")
    if content_text_provided:
        request_json["content_text"] = item.get("content_text")
    try:
        result = update_document_content(
            db_path,
            document_id=document_id,
            actor_id=actor_id,
            base_version=base_version,
            content=item.get("content"),
            content_text=item.get("content_text"),
            content_provided=content_provided,
            content_text_provided=content_text_provided,
            reason=request_json["reason"],
            merge_strategy=request_json["merge_strategy"],
        )
        status = "applied"
        result_json = result
        applied_event_id = result.get("event_id")
        applied_at = utc_now()
    except AppError as exc:
        status = "conflict" if exc.code == ErrorCode.VERSION_CONFLICT else "failed"
        result_json = exc.as_response()
        applied_event_id = None
        applied_at = None
    return _record_result(
        db_path,
        project_id=project_id,
        document_id=document_id,
        actor_id=actor_id,
        client_operation_id=client_operation_id,
        operation_type=operation_type,
        base_version=base_version,
        request_json=request_json,
        status=status,
        result_json=result_json,
        applied_event_id=applied_event_id,
        applied_at=applied_at,
    )


def _existing_result(db_path: str, *, actor_id: str, client_operation_id: str) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM offline_sync_operations
            WHERE actor_id = ? AND client_operation_id = ?
            """,
            (actor_id, client_operation_id),
        ).fetchone()
        if row is None:
            return None
        return _row_to_result(row, idempotent_replay=True)


def _record_result(
    db_path: str,
    *,
    project_id: str,
    document_id: str,
    actor_id: str,
    client_operation_id: str,
    operation_type: str,
    base_version: int,
    request_json: dict[str, Any],
    status: str,
    result_json: dict[str, Any],
    applied_event_id: str | None,
    applied_at: str | None,
) -> dict[str, Any]:
    operation_id = f"sync_{client_operation_id}"
    created_at = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO offline_sync_operations (
                id,
                project_id,
                document_id,
                actor_id,
                client_operation_id,
                operation_type,
                base_version,
                request_json,
                status,
                result_json,
                created_at,
                applied_event_id,
                applied_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                project_id,
                document_id,
                actor_id,
                client_operation_id,
                operation_type,
                base_version,
                json.dumps(request_json, sort_keys=True, separators=(",", ":")),
                status,
                json.dumps(result_json, sort_keys=True, separators=(",", ":")),
                created_at,
                applied_event_id,
                applied_at,
            ),
        )
        row = conn.execute("SELECT * FROM offline_sync_operations WHERE id = ?", (operation_id,)).fetchone()
        return _row_to_result(row, idempotent_replay=False)


def _row_to_result(row, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "client_operation_id": row["client_operation_id"],
        "operation_id": row["id"],
        "document_id": row["document_id"],
        "operation_type": row["operation_type"],
        "base_version": row["base_version"],
        "status": row["status"],
        "result": json.loads(row["result_json"]),
        "applied_event_id": row["applied_event_id"],
        "applied_at": row["applied_at"],
        "idempotent_replay": idempotent_replay,
    }


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppError(ErrorCode.INVALID_REQUEST, f"{field} is required.", {"field": field})
    return value.strip()
