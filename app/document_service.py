from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.database import connect, utc_now
from app.errors import AppError, ErrorCode
from app.json_patch import PatchApplyError, UnsupportedPatchOperationError, apply_patch
from app.json_pointer import JsonPointerError, get_value, join_pointer, parse_pointer
from app.path_validation import ensure_relative_document_path, ensure_relative_path_prefix
from app.permissions import ProjectPermission, ROLE_PERMISSIONS, require_actor, require_project_permission
from app.project_usage_service import ensure_project_usage_allows_snapshot
from app.replay import diff_json, replay_events
from app.schema_service import (
    get_schema_row,
    load_valid_bound_schema_json,
    load_valid_schema_json,
    resolve_schema_for_document,
    row_to_schema,
)
from app.schema_validation import ensure_schema_validates, validate_instance


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AppError(
            ErrorCode.INVALID_JSON_SYNTAX,
            "Value is not valid JSON.",
            {"message": str(exc)},
        ) from exc


def _json_pretty_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Canonical JSON document content could not be formatted.",
            {"message": str(exc)},
        ) from exc


def _json_loads(value: str) -> Any:
    return json.loads(value)


def _normalize_json(value: Any) -> Any:
    return _json_loads(_json_dumps(value))


def _ensure_canonical_document(value: Any) -> Any:
    normalized = _normalize_json(value)
    if not isinstance(normalized, (dict, list)):
        raise AppError(
            ErrorCode.INVALID_JSON_SYNTAX,
            "Canonical JSON document content must be an object or array.",
            {"actual_type": type(normalized).__name__},
        )
    return normalized


def _resolve_candidate_content(
    *,
    content: Any = None,
    content_text: str | None = None,
    content_provided: bool | None = None,
    content_text_provided: bool | None = None,
) -> tuple[Any, str]:
    content_provided = content is not None if content_provided is None else content_provided
    content_text_provided = content_text is not None if content_text_provided is None else content_text_provided
    if content_provided == content_text_provided:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Provide exactly one of content or content_text.",
            {
                "content_provided": content_provided,
                "content_text_provided": content_text_provided,
            },
        )
    if content_text_provided:
        if not isinstance(content_text, str):
            raise AppError(
                ErrorCode.INVALID_JSON_SYNTAX,
                "content_text must be a JSON string.",
                {"actual_type": type(content_text).__name__},
            )
        try:
            return _json_loads(content_text), "content_text"
        except json.JSONDecodeError as exc:
            raise AppError(
                ErrorCode.INVALID_JSON_SYNTAX,
                "JSON text is malformed.",
                {"source": "content_text", **_json_decode_details("content_text", exc)},
            ) from exc
    return content, "content"


def _dump_field(value: Any) -> str:
    return _json_dumps(value)


def _load_field(row: sqlite3.Row, field: str) -> Any:
    return _json_loads(row[field])


_EVENT_JSON_FIELDS = ("patch", "inverse_patch", "changed_paths", "before_values", "after_values")


def _json_decode_details(field: str, error: json.JSONDecodeError) -> dict[str, Any]:
    return {
        "field": field,
        "message": error.msg,
        "line": error.lineno,
        "column": error.colno,
        "position": error.pos,
    }


def _safe_load_field(row: sqlite3.Row, field: str) -> tuple[Any, dict[str, Any] | None]:
    try:
        return _load_field(row, field), None
    except json.JSONDecodeError as exc:
        return None, _json_decode_details(field, exc)


def _malformed_snapshot_details(row: sqlite3.Row, error: json.JSONDecodeError) -> dict[str, Any]:
    return {
        "diagnostic_code": "SNAPSHOT_JSON_DECODE_FAILED",
        "document_id": row["id"],
        "project_id": row["project_id"],
        "full_path": row["full_path"],
        "current_version": row["current_version"],
        **_json_decode_details("current_snapshot_json", error),
    }


def _load_document_snapshot(row: sqlite3.Row) -> Any:
    try:
        return _load_field(row, "current_snapshot_json")
    except json.JSONDecodeError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Document current_snapshot_json is malformed.",
            _malformed_snapshot_details(row, exc),
        ) from exc


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _ensure_valid_full_path(full_path: str) -> None:
    ensure_relative_document_path(full_path, error_code=ErrorCode.PATCH_APPLY_FAILED)


def _ensure_project(conn: sqlite3.Connection, project_id: str) -> None:
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.PROJECT_NOT_FOUND,
            "Project not found.",
            {"project_id": project_id},
        )


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


def _active_document_row_with_permission(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    actor_id: str | None,
    permission: str,
) -> sqlite3.Row:
    require_actor(conn, actor_id)
    row = _active_document_row(conn, document_id)
    require_project_permission(
        conn,
        actor_id=actor_id,
        project_id=row["project_id"],
        permission=permission,
    )
    return row


def _document_row_with_permission(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    actor_id: str | None,
    permission: str,
) -> sqlite3.Row:
    require_actor(conn, actor_id)
    row = _document_row_including_deleted(conn, document_id)
    require_project_permission(
        conn,
        actor_id=actor_id,
        project_id=row["project_id"],
        permission=permission,
    )
    return row


def _event_rows(conn: sqlite3.Connection, document_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT *
            FROM document_events
            WHERE document_id = ?
            ORDER BY result_version ASC
            """,
            (document_id,),
        ).fetchall()
    )


def _row_to_document(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "full_path": row["full_path"],
        "current_version": row["current_version"],
        "schema_id": row["schema_id"],
        "content": _load_document_snapshot(row),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted_at": row["deleted_at"],
    }


def _row_to_document_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "full_path": row["full_path"],
        "current_version": row["current_version"],
        "schema_id": row["schema_id"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "deleted_at": row["deleted_at"],
    }


def _row_to_project_summary(row: sqlite3.Row, role: str) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "role": role,
    }


def _row_to_event_metadata(row: sqlite3.Row) -> dict[str, Any]:
    return {
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


def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    event = _row_to_event_metadata(row)
    for field in _EVENT_JSON_FIELDS:
        event[field] = _load_field(row, field)
    return event


def _row_to_event_with_json_errors(row: sqlite3.Row) -> dict[str, Any]:
    event = _row_to_event_metadata(row)
    json_errors = []
    for field in _EVENT_JSON_FIELDS:
        event[field], error = _safe_load_field(row, field)
        if error:
            json_errors.append(error)
    if json_errors:
        event["json_errors"] = json_errors
    return event


def _row_to_event_detail(row: sqlite3.Row) -> dict[str, Any]:
    return _row_to_event_with_json_errors(row)


def _row_to_project_document_event(row: sqlite3.Row) -> dict[str, Any]:
    event = _row_to_event_with_json_errors(row)
    return {
        "id": event["id"],
        "document_id": event["document_id"],
        "project_id": row["project_id"],
        "full_path": row["full_path"],
        **{key: value for key, value in event.items() if key not in {"id", "document_id"}},
    }


def _event_detail_snapshot_error(
    *,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error = {
        "code": error_code,
        "message": message,
    }
    if details:
        error["details"] = details
    return error


def _malformed_event_json_details(event: dict[str, Any], failures: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "diagnostic_code": "EVENT_JSON_DECODE_FAILED",
        "event_id": event["id"],
        "document_id": event["document_id"],
        "base_version": event["base_version"],
        "result_version": event["result_version"],
        "failures": failures,
    }


def _event_replay_error(event: dict[str, Any], failures: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "code": "EVENT_JSON_DECODE_FAILED",
        "message": "Stored document event JSON field is malformed.",
        "details": _malformed_event_json_details(event, failures),
    }


def _raise_malformed_event_json(event: dict[str, Any]) -> None:
    raise AppError(
        ErrorCode.INTERNAL_ERROR,
        "Stored document event JSON field is malformed.",
        _malformed_event_json_details(event, event["json_errors"]),
    )


def _stored_event_replay_error(event: dict[str, Any], error: AppError) -> dict[str, Any]:
    return {
        "code": error.code,
        "message": error.message,
        "details": {
            "event_id": event["id"],
            "document_id": event["document_id"],
            "base_version": event["base_version"],
            "result_version": event["result_version"],
            "error_details": error.details,
        },
    }


def _validate_json_pointer(path: str) -> None:
    try:
        parse_pointer(path)
    except JsonPointerError as exc:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "path must be a valid JSON Pointer.",
            {"path": path, "message": str(exc)},
        ) from exc


def _path_value_record(document: Any, path: str, *, state_exists: bool) -> dict[str, Any]:
    if not state_exists:
        return {"exists": False, "value": None}
    try:
        return {"exists": True, "value": get_value(document, path)}
    except JsonPointerError:
        return {"exists": False, "value": None}


def _records_differ(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return before["exists"] != after["exists"] or before["value"] != after["value"]


def _apply_event_patch_for_history(state: Any, event: dict[str, Any], *, state_exists: bool) -> tuple[Any, bool]:
    if not event["patch"]:
        return state, state_exists
    try:
        next_state = apply_patch(state if state_exists else None, event["patch"]).document
    except PatchApplyError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Stored document event replay failed.",
            {"event_id": event["id"], "message": str(exc)},
        ) from exc
    return next_state, True


def _insert_event(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    actor_id: str,
    validation_schema_id: str | None,
    event_type: str,
    base_version: int,
    result_version: int,
    patch: list[dict[str, Any]],
    inverse_patch: list[dict[str, Any]],
    changed_paths: list[str],
    before_values: list[dict[str, Any]],
    after_values: list[dict[str, Any]],
    summary: str,
    reason: str | None,
) -> str:
    event_id = _new_id("evt")
    try:
        conn.execute(
            """
            INSERT INTO document_events (
                id,
                document_id,
                actor_id,
                validation_schema_id,
                event_type,
                base_version,
                result_version,
                patch,
                inverse_patch,
                changed_paths,
                before_values,
                after_values,
                summary,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                document_id,
                actor_id,
                validation_schema_id,
                event_type,
                base_version,
                result_version,
                _dump_field(patch),
                _dump_field(inverse_patch),
                _dump_field(changed_paths),
                _dump_field(before_values),
                _dump_field(after_values),
                summary,
                reason,
                utc_now(),
            ),
        )
    except sqlite3.DatabaseError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Document event could not be stored.",
            {"document_id": document_id, "result_version": result_version, "message": str(exc)},
        ) from exc
    return event_id


def _update_current_snapshot(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    snapshot: Any,
    version: int,
) -> None:
    try:
        conn.execute(
            """
            UPDATE json_documents
            SET current_snapshot_json = ?,
                current_version = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (_dump_field(snapshot), version, utc_now(), document_id),
        )
    except sqlite3.DatabaseError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Document snapshot update failed.",
            {"document_id": document_id, "version": version, "message": str(exc)},
        ) from exc


def _mark_document_deleted(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    version: int,
    deleted_at: str,
) -> None:
    try:
        conn.execute(
            """
            UPDATE json_documents
            SET current_version = ?,
                updated_at = ?,
                deleted_at = ?
            WHERE id = ?
            """,
            (version, deleted_at, deleted_at, document_id),
        )
    except sqlite3.DatabaseError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Document soft delete update failed.",
            {"document_id": document_id, "version": version, "message": str(exc)},
        ) from exc


def _mark_document_restored(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    version: int,
) -> None:
    try:
        conn.execute(
            """
            UPDATE json_documents
            SET current_version = ?,
                updated_at = ?,
                deleted_at = NULL
            WHERE id = ?
            """,
            (version, utc_now(), document_id),
        )
    except sqlite3.DatabaseError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Document restore update failed.",
            {"document_id": document_id, "version": version, "message": str(exc)},
        ) from exc


def _latest_event_for_conflict(conn: sqlite3.Connection, document_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, event_type, base_version, result_version, actor_id, created_at
        FROM document_events
        WHERE document_id = ?
        ORDER BY result_version DESC, id DESC
        LIMIT 1
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "event_type": row["event_type"],
        "base_version": row["base_version"],
        "result_version": row["result_version"],
        "actor_id": row["actor_id"],
        "created_at": row["created_at"],
    }


def _check_base_version(conn: sqlite3.Connection, row: sqlite3.Row, base_version: int) -> None:
    current_version = row["current_version"]
    if base_version != current_version:
        raise AppError(
            ErrorCode.VERSION_CONFLICT,
            "Document version conflict. Please reload the latest version.",
            {
                "client_base_version": base_version,
                "server_current_version": current_version,
                "document_id": row["id"],
                "project_id": row["project_id"],
                "full_path": row["full_path"],
                "conflict_policy": "reject_stale_base_version",
                "reload": {
                    "method": "GET",
                    "endpoint": f"/documents/{row['id']}/editor-state",
                },
                "latest_event": _latest_event_for_conflict(conn, row["id"]),
            },
        )


def _ensure_patch_changes_snapshot(current_snapshot: Any, next_snapshot: Any) -> None:
    if next_snapshot == current_snapshot:
        raise AppError(
            ErrorCode.PATCH_APPLY_FAILED,
            "Patch could not be applied.",
            {"message": "Patch does not change document content."},
        )


def _last_pointer_token_as_index(path: str) -> int:
    tokens = parse_pointer(path)
    if not tokens:
        return -1
    try:
        return int(tokens[-1])
    except ValueError:
        return -1


def _removal_sort_key(operation: dict[str, Any]) -> tuple[tuple[str, ...], int]:
    tokens = parse_pointer(operation["path"])
    if not tokens:
        return ((), -1)
    return (tuple(tokens[:-1]), _last_pointer_token_as_index(operation["path"]))


def _diff_changes_to_patch(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    value_operations: list[dict[str, Any]] = []
    remove_operations: list[dict[str, Any]] = []
    for change in changes:
        change_type = change["change_type"]
        path = change["path"]
        if change_type == "added":
            value_operations.append({"op": "add", "path": path, "value": change["after"]})
        elif change_type == "modified":
            value_operations.append({"op": "replace", "path": path, "value": change["after"]})
        elif change_type == "removed":
            remove_operations.append({"op": "remove", "path": path})
        else:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "Unexpected JSON diff change type.",
                {"change_type": change_type, "path": path},
            )

    # Removing array elements in descending index order avoids index shifts while
    # preserving the same final snapshot as the recursive diff.
    remove_operations.sort(key=_removal_sort_key, reverse=True)
    return value_operations + remove_operations


def _generate_patch_for_candidate_content(current_snapshot: Any, content: Any) -> tuple[Any, list[dict[str, Any]]]:
    candidate_content = _ensure_canonical_document(content)
    _ensure_patch_changes_snapshot(current_snapshot, candidate_content)
    return candidate_content, _diff_changes_to_patch(diff_json(current_snapshot, candidate_content))


def _pointer_from_tokens(tokens: tuple[str, ...]) -> str:
    path = ""
    for token in tokens:
        path = join_pointer(path, token)
    return path


def _paths_overlap(left_path: str, right_path: str) -> tuple[bool, str]:
    left_tokens = tuple(parse_pointer(left_path))
    right_tokens = tuple(parse_pointer(right_path))
    common_length = min(len(left_tokens), len(right_tokens))
    if left_tokens[:common_length] != right_tokens[:common_length]:
        return False, ""
    return True, _pointer_from_tokens(left_tokens if len(left_tokens) <= len(right_tokens) else right_tokens)


def _conflict_details(
    client_changes: list[dict[str, Any]],
    server_changes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    conflicts: list[dict[str, Any]] = []
    conflict_paths: set[str] = set()
    for client_change in client_changes:
        for server_change in server_changes:
            overlaps, conflict_path = _paths_overlap(client_change["path"], server_change["path"])
            if not overlaps:
                continue
            conflict_paths.add(conflict_path)
            conflicts.append(
                {
                    "path": conflict_path,
                    "client_path": client_change["path"],
                    "server_path": server_change["path"],
                    "client_change_type": client_change["change_type"],
                    "server_change_type": server_change["change_type"],
                    "client_before": client_change["before"],
                    "client_after": client_change["after"],
                    "server_before": server_change["before"],
                    "server_after": server_change["after"],
                }
            )
    conflicts.sort(key=lambda item: (item["path"], item["client_path"], item["server_path"]))
    return conflicts, sorted(conflict_paths)


def _path_touches_array(snapshot: Any, path: str) -> bool:
    node = snapshot
    if isinstance(node, list):
        return True
    for token in parse_pointer(path):
        if isinstance(node, list):
            return True
        if isinstance(node, dict) and token in node:
            node = node[token]
            continue
        return False
    return isinstance(node, list)


def _array_sensitive_change_paths(
    changes: list[dict[str, Any]],
    *,
    base_snapshot: Any,
    current_snapshot: Any,
    candidate_snapshot: Any,
) -> list[str]:
    paths: set[str] = set()
    for change in changes:
        path = change["path"]
        if isinstance(change.get("before"), list) or isinstance(change.get("after"), list):
            paths.add(path)
            continue
        if (
            _path_touches_array(base_snapshot, path)
            or _path_touches_array(current_snapshot, path)
            or _path_touches_array(candidate_snapshot, path)
        ):
            paths.add(path)
    return sorted(paths)


def _raise_auto_merge_conflict(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    base_version: int,
    conflicts: list[dict[str, Any]],
    conflicting_paths: list[str],
    array_paths: list[str] | None = None,
) -> None:
    raise AppError(
        ErrorCode.VERSION_CONFLICT,
        "Document version conflict. Auto-merge could not be applied safely.",
        {
            "client_base_version": base_version,
            "server_current_version": row["current_version"],
            "document_id": row["id"],
            "project_id": row["project_id"],
            "full_path": row["full_path"],
            "conflict_policy": "safe_path_auto_merge",
            "auto_merge": {
                "attempted": True,
                "status": "rejected",
                "reason": "array_path_changed" if array_paths else "overlapping_paths",
                "conflicting_paths": conflicting_paths,
                "array_paths": array_paths or [],
                "conflicts": conflicts,
            },
            "reload": {
                "method": "GET",
                "endpoint": f"/documents/{row['id']}/editor-state",
            },
            "latest_event": _latest_event_for_conflict(conn, row["id"]),
        },
    )


def _ensure_preview_base_version(row: sqlite3.Row, base_version: int) -> None:
    current_version = row["current_version"]
    if base_version <= 0 or base_version > current_version:
        raise AppError(
            ErrorCode.INVALID_VERSION_RANGE,
            "base_version must be a positive existing document version.",
            {
                "base_version": base_version,
                "server_current_version": current_version,
                "document_id": row["id"],
                "project_id": row["project_id"],
                "full_path": row["full_path"],
            },
        )


def create_document_in_transaction(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    actor_id: str,
    full_path: str,
    content: Any,
    schema_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    _ensure_valid_full_path(full_path)
    now = utc_now()
    document_id = _new_id("doc")

    require_project_permission(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        permission=ProjectPermission.DOCUMENT_WRITE,
    )
    schema_row = resolve_schema_for_document(
        conn,
        project_id=project_id,
        full_path=full_path,
        schema_id=schema_id,
    )
    normalized_content = _ensure_canonical_document(content)
    validation = {"valid": True, "errors": [], "warnings": []}
    resolved_schema_id = None
    if schema_row is not None:
        resolved_schema_id = schema_row["id"]
        validation = ensure_schema_validates(load_valid_schema_json(schema_row), normalized_content)
    ensure_project_usage_allows_snapshot(
        conn,
        project_id=project_id,
        candidate_snapshot=normalized_content,
        document_count_delta=1,
    )
    patch = [{"op": "add", "path": "", "value": normalized_content}]
    before_values = [{"path": "", "exists": False, "value": None}]
    after_values = [{"path": "", "exists": True, "value": normalized_content}]
    try:
        conn.execute(
            """
            INSERT INTO json_documents (
                id,
                project_id,
                full_path,
                current_version,
                current_snapshot_json,
                schema_id,
                created_by,
                created_at,
                updated_at,
                deleted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                document_id,
                project_id,
                full_path,
                1,
                _dump_field(normalized_content),
                resolved_schema_id,
                actor_id,
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise AppError(
            ErrorCode.PATCH_APPLY_FAILED,
            "Document path already exists or project reference is invalid.",
            {"project_id": project_id, "full_path": full_path},
        ) from exc
    event_id = _insert_event(
        conn,
        document_id=document_id,
        actor_id=actor_id,
        validation_schema_id=resolved_schema_id,
        event_type="create",
        base_version=0,
        result_version=1,
        patch=patch,
        inverse_patch=[{"op": "remove", "path": ""}],
        changed_paths=[""],
        before_values=before_values,
        after_values=after_values,
        summary=f"Created {full_path}",
        reason=reason,
    )
    row = _active_document_row(conn, document_id)
    response = _row_to_document(row)
    response["event_id"] = event_id
    response["event_type"] = "create"
    response["validation"] = validation
    return response


def create_document(
    db_path: str,
    *,
    project_id: str,
    actor_id: str,
    full_path: str,
    content: Any,
    schema_id: str | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        return create_document_in_transaction(
            conn,
            project_id=project_id,
            actor_id=actor_id,
            full_path=full_path,
            content=content,
            schema_id=schema_id,
        )


def get_document(db_path: str, document_id: str, *, actor_id: str | None) -> dict[str, Any]:
    with connect(db_path) as conn:
        return _row_to_document(
            _active_document_row_with_permission(
                conn,
                document_id=document_id,
                actor_id=actor_id,
                permission=ProjectPermission.DOCUMENT_READ,
            )
        )


def _editor_capabilities(role: str) -> dict[str, bool]:
    permissions = ROLE_PERMISSIONS.get(role, set())
    return {
        "can_read": ProjectPermission.DOCUMENT_READ in permissions,
        "can_patch": ProjectPermission.DOCUMENT_WRITE in permissions,
        "can_patch_preview": ProjectPermission.DOCUMENT_WRITE in permissions,
        "can_delete": ProjectPermission.DOCUMENT_DELETE in permissions,
        "can_restore": False,
        "can_rollback": ProjectPermission.DOCUMENT_ROLLBACK in permissions,
        "can_validate": ProjectPermission.DOCUMENT_VALIDATE in permissions,
        "can_comment": ProjectPermission.COMMENT_WRITE in permissions,
        "can_create_review": ProjectPermission.REVIEW_CREATE in permissions,
    }


def _editor_workflow_contract(
    *,
    document_id: str,
    current_version: int,
    capabilities: dict[str, bool],
) -> dict[str, Any]:
    document_endpoint = f"/documents/{document_id}"
    editor_state_endpoint = f"{document_endpoint}/editor-state"
    return {
        "mode": "non_realtime_versioned_edit",
        "canonical_source": "document.content",
        "raw_text_source": "document.content_text",
        "base_version_field": "base_version",
        "required_base_version": current_version,
        "supported_content_sources": ["content", "content_text"],
        "save_contract": {
            "accepted_event_required": True,
            "snapshot_update_requires_event": True,
            "invalid_json_persistence": "reject",
            "conflict_policy": "reject_stale_base_version",
            "conflict_error_code": ErrorCode.VERSION_CONFLICT,
            "recovery": [
                "GET /documents/{document_id}/editor-state",
                "POST /documents/{document_id}/content-conflict-preview",
                "PUT /documents/{document_id}/content with latest base_version",
            ],
        },
        "actions": {
            "reload": {
                "method": "GET",
                "endpoint": editor_state_endpoint,
                "available": capabilities["can_read"],
                "read_only": True,
            },
            "validate_current": {
                "method": "POST",
                "endpoint": f"{document_endpoint}/validate",
                "available": capabilities["can_validate"],
                "read_only": True,
            },
            "preview_patch": {
                "method": "POST",
                "endpoint": f"{document_endpoint}/patch-preview",
                "available": capabilities["can_patch_preview"],
                "read_only": True,
                "requires_current_base_version": True,
            },
            "preview_content": {
                "method": "POST",
                "endpoint": f"{document_endpoint}/content-preview",
                "available": capabilities["can_patch_preview"],
                "read_only": True,
                "requires_current_base_version": True,
            },
            "preview_content_conflict": {
                "method": "POST",
                "endpoint": f"{document_endpoint}/content-conflict-preview",
                "available": capabilities["can_patch_preview"],
                "read_only": True,
                "allows_stale_existing_base_version": True,
            },
            "save_patch": {
                "method": "PATCH",
                "endpoint": document_endpoint,
                "available": capabilities["can_patch"],
                "read_only": False,
                "requires_current_base_version": True,
                "creates_document_event": True,
            },
            "save_content": {
                "method": "PUT",
                "endpoint": f"{document_endpoint}/content",
                "available": capabilities["can_patch"],
                "read_only": False,
                "requires_current_base_version": True,
                "creates_document_event": True,
            },
            "history": {
                "method": "GET",
                "endpoint": f"{document_endpoint}/history",
                "available": capabilities["can_read"],
                "read_only": True,
            },
            "diff": {
                "method": "GET",
                "endpoint": f"{document_endpoint}/diff",
                "available": capabilities["can_read"],
                "read_only": True,
                "query": {"from_version": 1, "to_version": current_version},
            },
            "rollback": {
                "method": "POST",
                "endpoint": f"{document_endpoint}/rollback",
                "available": capabilities["can_rollback"],
                "read_only": False,
                "requires_current_base_version": True,
                "creates_document_event": True,
            },
        },
        "state_machine": _editor_state_machine_contract(capabilities=capabilities),
    }


def _actions_if_available(capabilities: dict[str, bool], action_names: list[str]) -> list[str]:
    requirements = {
        "validate_current": "can_validate",
        "preview_patch": "can_patch_preview",
        "preview_content": "can_patch_preview",
        "preview_content_conflict": "can_patch_preview",
        "save_patch": "can_patch",
        "save_content": "can_patch",
        "rollback": "can_rollback",
    }
    available: list[str] = []
    for action_name in action_names:
        required_capability = requirements.get(action_name)
        if required_capability is None or capabilities[required_capability]:
            available.append(action_name)
    return available


def _editor_state_machine_contract(*, capabilities: dict[str, bool]) -> dict[str, Any]:
    read_actions = _actions_if_available(capabilities, ["reload", "validate_current", "history", "diff"])
    edit_actions = _actions_if_available(capabilities, ["preview_patch", "preview_content"])
    save_actions = _actions_if_available(capabilities, ["save_patch", "save_content"])
    conflict_actions = _actions_if_available(capabilities, ["preview_content_conflict", "reload", "history", "diff"])
    return {
        "version": "task094.non_realtime_editor_state_machine.v1",
        "initial_state": "clean" if capabilities["can_patch"] else "read_only",
        "client_owned_states": ["dirty", "syntax_invalid", "previewing", "saving"],
        "server_verified_states": [
            "read_only",
            "clean",
            "preview_ready",
            "saved",
            "validation_failed",
            "stale_conflict",
            "conflict_preview",
        ],
        "states": {
            "read_only": {
                "can_persist": False,
                "creates_document_event": False,
                "allowed_actions": read_actions,
            },
            "clean": {
                "can_persist": False,
                "creates_document_event": False,
                "allowed_actions": read_actions + edit_actions,
            },
            "dirty": {
                "can_persist": False,
                "creates_document_event": False,
                "allowed_actions": edit_actions + read_actions,
            },
            "syntax_invalid": {
                "can_persist": False,
                "creates_document_event": False,
                "allowed_actions": ["reload", "history", "diff"],
            },
            "previewing": {
                "can_persist": False,
                "creates_document_event": False,
                "allowed_actions": ["reload"],
            },
            "preview_ready": {
                "can_persist": bool(save_actions),
                "creates_document_event": False,
                "allowed_actions": save_actions + edit_actions + read_actions,
            },
            "saving": {
                "can_persist": False,
                "creates_document_event": False,
                "allowed_actions": [],
            },
            "saved": {
                "can_persist": False,
                "creates_document_event": True,
                "allowed_actions": ["reload", "history", "diff"],
            },
            "validation_failed": {
                "can_persist": False,
                "creates_document_event": False,
                "allowed_actions": edit_actions + read_actions,
            },
            "stale_conflict": {
                "can_persist": False,
                "creates_document_event": False,
                "allowed_actions": conflict_actions,
            },
            "conflict_preview": {
                "can_persist": False,
                "creates_document_event": False,
                "allowed_actions": conflict_actions,
            },
        },
        "transitions": [
            {"from": "clean", "on": "local_edit", "to": "dirty"},
            {"from": "dirty", "on": "content_text_parse_error", "to": "syntax_invalid"},
            {"from": "syntax_invalid", "on": "local_edit", "to": "dirty"},
            {"from": "dirty", "on": "preview_started", "to": "previewing"},
            {"from": "previewing", "on": "preview_success", "to": "preview_ready"},
            {"from": "previewing", "on": "schema_validation_failed", "to": "validation_failed"},
            {"from": "previewing", "on": "version_conflict", "to": "stale_conflict"},
            {"from": "preview_ready", "on": "save_started", "to": "saving"},
            {"from": "saving", "on": "save_success", "to": "saved"},
            {"from": "saving", "on": "version_conflict", "to": "stale_conflict"},
            {"from": "saving", "on": "schema_validation_failed", "to": "validation_failed"},
            {"from": "stale_conflict", "on": "content_conflict_preview_success", "to": "conflict_preview"},
            {"from": "stale_conflict", "on": "reload_success", "to": "clean"},
            {"from": "conflict_preview", "on": "reload_success", "to": "clean"},
            {"from": "saved", "on": "accept_latest_as_base", "to": "clean"},
        ],
        "event_creation": {
            "only_on": ["save_success"],
            "never_on": [
                "preview_success",
                "content_conflict_preview_success",
                "content_text_parse_error",
                "schema_validation_failed",
                "version_conflict",
                "reload_success",
            ],
        },
    }


def _document_validation_result(conn: sqlite3.Connection, row: sqlite3.Row, snapshot: Any) -> dict[str, Any]:
    if not row["schema_id"]:
        return {
            "valid": True,
            "errors": [],
            "warnings": [
                {
                    "path": "",
                    "message": "Document has no schema binding.",
                    "validation_level": "schema",
                    "severity": "warning",
                }
            ],
        }
    result = validate_instance(load_valid_bound_schema_json(conn, row["schema_id"]), snapshot)
    return {
        "valid": result["valid"],
        "errors": result["errors"],
        "warnings": result["warnings"],
    }


def _editor_validation_state(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    snapshot: Any,
    include_validation: bool,
    can_validate: bool,
) -> dict[str, Any]:
    if not include_validation:
        return {"available": False, "reason": "not_requested"}
    if not can_validate:
        return {"available": False, "reason": "permission_denied"}
    try:
        return {"available": True, **_document_validation_result(conn, row, snapshot)}
    except AppError as exc:
        diagnostic_code = exc.details.get("diagnostic_code")
        if exc.code == ErrorCode.INTERNAL_ERROR and diagnostic_code in {
            "SCHEMA_JSON_DECODE_FAILED",
            "SCHEMA_JSON_SCHEMA_INVALID",
        }:
            return {
                "available": False,
                "reason": "schema_unavailable",
                "error": exc.as_response()["error"],
            }
        raise


def _recent_document_events(conn: sqlite3.Connection, document_id: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM document_events
        WHERE document_id = ?
        ORDER BY result_version DESC
        LIMIT ?
        """,
        (document_id, limit),
    ).fetchall()
    return [_row_to_event_with_json_errors(row) for row in rows]


def _ensure_recent_events_limit(recent_events_limit: int) -> None:
    if recent_events_limit < 0 or recent_events_limit > 50:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "recent_events_limit must be between 0 and 50.",
            {"recent_events_limit": recent_events_limit},
        )


def _document_editor_state_from_row(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    actor_id: str | None,
    role: str,
    include_validation: bool,
    recent_events_limit: int,
) -> dict[str, Any]:
    snapshot = _load_document_snapshot(row)
    capabilities = _editor_capabilities(role)
    schema = row_to_schema(get_schema_row(conn, row["schema_id"])) if row["schema_id"] else None
    document = _row_to_document(row)
    document["content_text"] = _json_pretty_dumps(snapshot)
    document["content_text_format"] = {
        "encoding": "utf-8",
        "indent": 2,
        "sort_keys": True,
        "source": "current_snapshot_json",
    }
    return {
        "document": document,
        "editor": {
            "actor_id": actor_id,
            "role": role,
            "capabilities": capabilities,
            "required_base_version": row["current_version"],
            "supported_patch_operations": ["add", "replace", "remove"],
            "conflict_policy": "reject_stale_base_version",
            "persistence": "validated_document_event",
        },
        "workflow": _editor_workflow_contract(
            document_id=row["id"],
            current_version=row["current_version"],
            capabilities=capabilities,
        ),
        "schema": schema,
        "validation": _editor_validation_state(
            conn,
            row=row,
            snapshot=snapshot,
            include_validation=include_validation,
            can_validate=capabilities["can_validate"],
        ),
        "recent_events": _recent_document_events(conn, row["id"], recent_events_limit),
    }


def get_document_editor_state(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
    include_validation: bool = True,
    recent_events_limit: int = 10,
) -> dict[str, Any]:
    _ensure_recent_events_limit(recent_events_limit)
    with connect(db_path) as conn:
        require_actor(conn, actor_id)
        row = _active_document_row(conn, document_id)
        role = require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=ProjectPermission.DOCUMENT_READ,
        )
        return _document_editor_state_from_row(
            conn,
            row=row,
            actor_id=actor_id,
            role=role,
            include_validation=include_validation,
            recent_events_limit=recent_events_limit,
        )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _ensure_list_filter_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if "\\" in normalized:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"{field} must use POSIX-style '/' separators.",
            {field: value},
        )
    return normalized


DOCUMENT_EVENT_TYPES = {"create", "update", "delete", "restore", "rollback"}


def _ensure_event_type_filter(event_type: str | None) -> str | None:
    if event_type is None:
        return None
    normalized = event_type.strip()
    if normalized not in DOCUMENT_EVENT_TYPES:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "event_type must be one of the supported document event types.",
            {"event_type": event_type, "allowed_event_types": sorted(DOCUMENT_EVENT_TYPES)},
        )
    return normalized


def _ensure_search_query(q: str) -> str:
    normalized = q.strip()
    if not normalized:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "q must not be empty.",
            {"q": q},
        )
    return normalized


def _json_search_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return _json_dumps(value)
    return None


def _iter_json_search_matches(value: Any, query_text: str, path: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = join_pointer(path, key)
            if query_text in key.casefold():
                matches.append(
                    {
                        "match_type": "key",
                        "path": child_path,
                        "key": key,
                        "value": child,
                    }
                )
            matches.extend(_iter_json_search_matches(child, query_text, child_path))
        return matches
    if isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(_iter_json_search_matches(child, query_text, join_pointer(path, str(index))))
        return matches

    searchable = _json_search_text(value)
    if searchable is not None and query_text in searchable.casefold():
        matches.append(
            {
                "match_type": "value",
                "path": path,
                "key": None,
                "value": value,
            }
        )
    return matches


def _document_search_result(
    row: sqlite3.Row,
    *,
    q: str,
    path: str | None,
    max_matches_per_document: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    query_text = q.casefold()
    matches: list[dict[str, Any]] = []
    if path is None and query_text in row["full_path"].casefold():
        matches.append(
            {
                "match_type": "full_path",
                "path": None,
                "key": None,
                "value": row["full_path"],
            }
        )

    snapshot_error = None
    try:
        snapshot = _load_field(row, "current_snapshot_json")
    except json.JSONDecodeError as exc:
        snapshot_error = _malformed_snapshot_details(row, exc)
    else:
        search_root_path = path or ""
        try:
            search_root = get_value(snapshot, search_root_path)
        except JsonPointerError:
            content_matches: list[dict[str, Any]] = []
        else:
            content_matches = _iter_json_search_matches(search_root, query_text, search_root_path)
        matches.extend(content_matches)
    if not matches:
        return None, snapshot_error

    document = _row_to_document_summary(row)
    document["match_count"] = len(matches)
    document["matches_truncated"] = len(matches) > max_matches_per_document
    document["matches"] = matches[:max_matches_per_document]
    if snapshot_error:
        document["snapshot_error"] = snapshot_error
    return document, snapshot_error


def _new_tree_folder(name: str, path: str) -> dict[str, Any]:
    return {
        "type": "folder",
        "name": name,
        "path": path,
        "document_count": 0,
        "children": [],
    }


def _normalize_tree_folder(folder: dict[str, Any]) -> dict[str, Any]:
    child_folders = [_normalize_tree_folder(child) for child in folder.pop("_folders").values()]
    documents = folder.pop("_documents")
    folder["children"] = [
        *sorted(child_folders, key=lambda item: item["name"]),
        *sorted(documents, key=lambda item: item["name"]),
    ]
    return folder


def _add_document_to_tree(
    root: dict[str, Any],
    document: dict[str, Any],
    relative_path: str,
    *,
    base_path: str = "",
) -> int:
    segments = [segment for segment in relative_path.split("/") if segment]
    if not segments:
        return 0
    current = root
    created_folders = 0
    for index, segment in enumerate(segments[:-1]):
        child_path = "/".join(part for part in (base_path, *segments[: index + 1]) if part)
        if child_path not in current["_folders"]:
            current["_folders"][child_path] = {
                **_new_tree_folder(segment, child_path),
                "_folders": {},
                "_documents": [],
            }
            created_folders += 1
        current = current["_folders"][child_path]
        current["document_count"] += 1
    current["_documents"].append(
        {
            "type": "document",
            "name": segments[-1],
            "path": document["full_path"],
            "document": document,
        }
    )
    root["document_count"] += 1
    return created_folders


def _ensure_document_page(limit: int, offset: int) -> None:
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


def _project_document_rows(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    include_deleted: bool,
    path_prefix: str | None,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    include_prefix_document: bool = True,
) -> tuple[list[sqlite3.Row], int]:
    where = ["project_id = ?"]
    params: list[Any] = [project_id]
    if not include_deleted:
        where.append("deleted_at IS NULL")
    if path_prefix is not None:
        if include_prefix_document:
            where.append("(full_path = ? OR full_path LIKE ? ESCAPE '\\')")
            params.extend([path_prefix, f"{_escape_like(path_prefix)}/%"])
        else:
            where.append("full_path LIKE ? ESCAPE '\\'")
            params.append(f"{_escape_like(path_prefix)}/%")
    if q is not None:
        where.append("LOWER(full_path) LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(q.lower())}%")
    where_sql = " AND ".join(where)

    total = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM json_documents
        WHERE {where_sql}
        """,
        params,
    ).fetchone()["count"]
    if limit is None:
        rows = conn.execute(
            f"""
            SELECT *
            FROM json_documents
            WHERE {where_sql}
            ORDER BY full_path ASC, id ASC
            """,
            params,
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT *
            FROM json_documents
            WHERE {where_sql}
            ORDER BY full_path ASC, id ASC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    return rows, total


def _project_document_list_from_rows(
    *,
    project_id: str,
    rows: list[sqlite3.Row],
    total: int,
    include_deleted: bool,
    path_prefix: str | None,
    q: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    documents = [_row_to_document_summary(row) for row in rows]
    return {
        "project_id": project_id,
        "documents": documents,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total": total,
            "has_more": offset + len(documents) < total,
        },
        "filters": {
            "include_deleted": include_deleted,
            "path_prefix": path_prefix,
            "q": q,
        },
    }


def _project_document_tree_from_rows(
    *,
    project_id: str,
    rows: list[sqlite3.Row],
    include_deleted: bool,
    path_prefix: str | None,
) -> dict[str, Any]:
    root_path = path_prefix or ""
    root_name = root_path.split("/")[-1] if root_path else ""
    root = {
        **_new_tree_folder(root_name, root_path),
        "_folders": {},
        "_documents": [],
    }
    deleted_count = 0
    folder_count = 0
    prefix_length = len(root_path) + 1 if root_path else 0
    for row in rows:
        document = _row_to_document_summary(row)
        if document["deleted_at"] is not None:
            deleted_count += 1
        relative_path = row["full_path"][prefix_length:] if root_path else row["full_path"]
        folder_count += _add_document_to_tree(root, document, relative_path, base_path=root_path)
    return {
        "project_id": project_id,
        "root": _normalize_tree_folder(root),
        "summary": {
            "document_count": root["document_count"],
            "folder_count": folder_count,
            "deleted_document_count": deleted_count,
        },
        "filters": {
            "include_deleted": include_deleted,
            "path_prefix": path_prefix,
        },
    }


def list_project_documents(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    include_deleted: bool = False,
    path_prefix: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    _ensure_document_page(limit, offset)
    path_prefix = ensure_relative_path_prefix(path_prefix, error_code=ErrorCode.INVALID_REQUEST)
    q = _ensure_list_filter_text(q, "q")

    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        rows, total = _project_document_rows(
            conn,
            project_id=project_id,
            include_deleted=include_deleted,
            path_prefix=path_prefix,
            q=q,
            limit=limit,
            offset=offset,
            include_prefix_document=True,
        )
        return _project_document_list_from_rows(
            project_id=project_id,
            rows=rows,
            total=total,
            include_deleted=include_deleted,
            path_prefix=path_prefix,
            q=q,
            limit=limit,
            offset=offset,
        )


def get_project_document_tree(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    include_deleted: bool = False,
    path_prefix: str | None = None,
) -> dict[str, Any]:
    path_prefix = ensure_relative_path_prefix(path_prefix, error_code=ErrorCode.INVALID_REQUEST)

    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        rows, _ = _project_document_rows(
            conn,
            project_id=project_id,
            include_deleted=include_deleted,
            path_prefix=path_prefix,
            limit=None,
            include_prefix_document=False,
        )

    return _project_document_tree_from_rows(
        project_id=project_id,
        rows=rows,
        include_deleted=include_deleted,
        path_prefix=path_prefix,
    )


def get_project_editor_bootstrap(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    selected_document_id: str | None = None,
    include_validation: bool = True,
    recent_events_limit: int = 10,
    include_deleted: bool = False,
    path_prefix: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    _ensure_document_page(limit, offset)
    _ensure_recent_events_limit(recent_events_limit)
    path_prefix = ensure_relative_path_prefix(path_prefix, error_code=ErrorCode.INVALID_REQUEST)
    q = _ensure_list_filter_text(q, "q")

    with connect(db_path) as conn:
        role = require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        project_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project_row is None:
            raise AppError(
                ErrorCode.PROJECT_NOT_FOUND,
                "Project not found.",
                {"project_id": project_id},
            )
        list_rows, list_total = _project_document_rows(
            conn,
            project_id=project_id,
            include_deleted=include_deleted,
            path_prefix=path_prefix,
            q=q,
            limit=limit,
            offset=offset,
            include_prefix_document=True,
        )
        tree_rows, _ = _project_document_rows(
            conn,
            project_id=project_id,
            include_deleted=include_deleted,
            path_prefix=path_prefix,
            limit=None,
            include_prefix_document=False,
        )
        selected_state = None
        if selected_document_id is not None:
            selected_row = conn.execute(
                """
                SELECT *
                FROM json_documents
                WHERE id = ? AND project_id = ? AND deleted_at IS NULL
                """,
                (selected_document_id, project_id),
            ).fetchone()
            if selected_row is None:
                raise AppError(
                    ErrorCode.DOCUMENT_NOT_FOUND,
                    "Document not found.",
                    {"document_id": selected_document_id, "project_id": project_id},
                )
            selected_state = _document_editor_state_from_row(
                conn,
                row=selected_row,
                actor_id=actor_id,
                role=role,
                include_validation=include_validation,
                recent_events_limit=recent_events_limit,
            )

    capabilities = _editor_capabilities(role)
    return {
        "project": _row_to_project_summary(project_row, role),
        "actor": {
            "id": actor_id,
            "role": role,
            "capabilities": capabilities,
        },
        "bootstrap": {
            "mode": "project_editor_bootstrap",
            "version": "task095.project_editor_bootstrap.v1",
            "read_only": True,
            "selected_document_id": selected_document_id,
            "include_selected_document": selected_state is not None,
            "selected_document_source": "GET /documents/{document_id}/editor-state",
            "event_creation": {
                "creates_document_event": False,
                "accepted_document_events_source": "document_events",
            },
            "actions": {
                "reload": {
                    "method": "GET",
                    "endpoint": f"/projects/{project_id}/editor-bootstrap",
                    "available": True,
                    "read_only": True,
                },
                "list_documents": {
                    "method": "GET",
                    "endpoint": f"/projects/{project_id}/documents",
                    "available": capabilities["can_read"],
                    "read_only": True,
                },
                "document_tree": {
                    "method": "GET",
                    "endpoint": f"/projects/{project_id}/document-tree",
                    "available": capabilities["can_read"],
                    "read_only": True,
                },
                "open_document": {
                    "method": "GET",
                    "endpoint": "/documents/{document_id}/editor-state",
                    "available": capabilities["can_read"],
                    "read_only": True,
                },
            },
        },
        "documents": _project_document_list_from_rows(
            project_id=project_id,
            rows=list_rows,
            total=list_total,
            include_deleted=include_deleted,
            path_prefix=path_prefix,
            q=q,
            limit=limit,
            offset=offset,
        ),
        "document_tree": _project_document_tree_from_rows(
            project_id=project_id,
            rows=tree_rows,
            include_deleted=include_deleted,
            path_prefix=path_prefix,
        ),
        "selected_document_editor_state": selected_state,
    }


def search_project_documents(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    q: str,
    path: str | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
    max_matches_per_document: int = 5,
) -> dict[str, Any]:
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
    if max_matches_per_document < 1 or max_matches_per_document > 20:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "max_matches_per_document must be between 1 and 20.",
            {"max_matches_per_document": max_matches_per_document},
        )
    q = _ensure_search_query(q)
    if path is not None:
        _validate_json_pointer(path)

    where = ["project_id = ?"]
    params: list[Any] = [project_id]
    if not include_deleted:
        where.append("deleted_at IS NULL")
    where_sql = " AND ".join(where)

    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        rows = conn.execute(
            f"""
            SELECT *
            FROM json_documents
            WHERE {where_sql}
            ORDER BY full_path ASC, id ASC
            """,
            params,
        ).fetchall()
        documents = []
        snapshot_errors = []
        for row in rows:
            result, snapshot_error = _document_search_result(
                row,
                q=q,
                path=path,
                max_matches_per_document=max_matches_per_document,
            )
            if snapshot_error:
                snapshot_errors.append(snapshot_error)
            if result is not None:
                documents.append(result)
        total = len(documents)
        page = documents[offset : offset + limit]
        return {
            "project_id": project_id,
            "status": "partial" if snapshot_errors else "ok",
            "documents": page,
            "snapshot_errors": snapshot_errors,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "has_more": offset + len(page) < total,
            },
            "filters": {
                "q": q,
                "path": path,
                "include_deleted": include_deleted,
                "max_matches_per_document": max_matches_per_document,
            },
        }


def list_project_document_events(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    event_type: str | None = None,
    event_actor_id: str | None = None,
    document_id: str | None = None,
    changed_path: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
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
    event_type = _ensure_event_type_filter(event_type)
    event_actor_id = _ensure_list_filter_text(event_actor_id, "actor_id")
    if document_id is not None:
        document_id = document_id.strip()
        if not document_id:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "document_id filter must not be empty.",
                {"document_id": document_id},
            )
    if changed_path is not None:
        _validate_json_pointer(changed_path)

    where = ["d.project_id = ?"]
    params: list[Any] = [project_id]
    if event_type is not None:
        where.append("e.event_type = ?")
        params.append(event_type)
    if event_actor_id is not None:
        where.append("e.actor_id = ?")
        params.append(event_actor_id)
    if document_id is not None:
        where.append("e.document_id = ?")
        params.append(document_id)
    where_sql = " AND ".join(where)

    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        if document_id is not None:
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
        rows = conn.execute(
            f"""
            SELECT e.*, d.project_id AS project_id, d.full_path AS full_path
            FROM document_events AS e
            JOIN json_documents AS d ON d.id = e.document_id
            WHERE {where_sql}
            ORDER BY e.created_at DESC, e.result_version DESC, e.id DESC
            """,
            params,
        ).fetchall()

        events = [_row_to_project_document_event(row) for row in rows]
        if changed_path is not None:
            events = [
                event
                for event in events
                if isinstance(event["changed_paths"], list) and changed_path in event["changed_paths"]
            ]
        total = len(events)
        page = events[offset : offset + limit]
        return {
            "project_id": project_id,
            "events": page,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "has_more": offset + len(page) < total,
            },
            "filters": {
                "event_type": event_type,
                "actor_id": event_actor_id,
                "document_id": document_id,
                "changed_path": changed_path,
            },
        }


def patch_document(
    db_path: str,
    *,
    document_id: str,
    actor_id: str,
    base_version: int,
    patch: list[dict[str, Any]],
    reason: str | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        # Event insert and snapshot update are intentionally inside one transaction.
        # If either write fails, ManagedConnection rolls the entire mutation back.
        conn.execute("BEGIN IMMEDIATE")
        row = _active_document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_WRITE,
        )
        return apply_document_patch_in_transaction(
            conn,
            actor_id=actor_id,
            row=row,
            base_version=base_version,
            patch=patch,
            reason=reason,
        )


def preview_document_patch(
    db_path: str,
    *,
    document_id: str,
    actor_id: str,
    base_version: int,
    patch: list[dict[str, Any]],
) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = _active_document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_WRITE,
        )
        preview = validate_document_patch_candidate(
            conn,
            row=row,
            base_version=base_version,
            patch=patch,
        )
        return {
            "document_id": row["id"],
            "project_id": row["project_id"],
            "full_path": row["full_path"],
            "base_version": base_version,
            "current_version": row["current_version"],
            "schema_id": row["schema_id"],
            "candidate_content": preview["candidate_content"],
            "changed_paths": preview["changed_paths"],
            "inverse_patch": preview["inverse_patch"],
            "before_values": preview["before_values"],
            "after_values": preview["after_values"],
            "validation": preview["validation"],
            "persisted": False,
        }


def preview_document_content_update(
    db_path: str,
    *,
    document_id: str,
    actor_id: str,
    base_version: int,
    content: Any = None,
    content_text: str | None = None,
    content_provided: bool | None = None,
    content_text_provided: bool | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = _active_document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_WRITE,
        )
        _check_base_version(conn, row, base_version)
        current_snapshot = _load_document_snapshot(row)
        candidate_content, content_source = _resolve_candidate_content(
            content=content,
            content_text=content_text,
            content_provided=content_provided,
            content_text_provided=content_text_provided,
        )
        _, generated_patch = _generate_patch_for_candidate_content(current_snapshot, candidate_content)
        preview = validate_document_patch_candidate(
            conn,
            row=row,
            base_version=base_version,
            patch=generated_patch,
        )
        return {
            "document_id": row["id"],
            "project_id": row["project_id"],
            "full_path": row["full_path"],
            "base_version": base_version,
            "current_version": row["current_version"],
            "schema_id": row["schema_id"],
            "candidate_content": preview["candidate_content"],
            "content_source": content_source,
            "generated_patch": generated_patch,
            "changed_paths": preview["changed_paths"],
            "inverse_patch": preview["inverse_patch"],
            "before_values": preview["before_values"],
            "after_values": preview["after_values"],
            "validation": preview["validation"],
            "persisted": False,
        }


def preview_document_content_conflict(
    db_path: str,
    *,
    document_id: str,
    actor_id: str,
    base_version: int,
    content: Any = None,
    content_text: str | None = None,
    content_provided: bool | None = None,
    content_text_provided: bool | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = _active_document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_WRITE,
        )
        _ensure_preview_base_version(row, base_version)
        current_snapshot = _load_document_snapshot(row)
        events = _events_for_replay(conn, row["id"])
        base_snapshot = replay_events(events, target_version=base_version)
        replayed_current_snapshot = replay_events(events, target_version=row["current_version"])
        if replayed_current_snapshot != current_snapshot:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "Event replay does not match latest snapshot.",
                {
                    "document_id": row["id"],
                    "project_id": row["project_id"],
                    "full_path": row["full_path"],
                    "current_version": row["current_version"],
                },
            )
        candidate_content, content_source = _resolve_candidate_content(
            content=content,
            content_text=content_text,
            content_provided=content_provided,
            content_text_provided=content_text_provided,
        )
        candidate_content = _ensure_canonical_document(candidate_content)
        validation = {"valid": True, "errors": [], "warnings": []}
        if row["schema_id"]:
            validation = ensure_schema_validates(load_valid_bound_schema_json(conn, row["schema_id"]), candidate_content)
        client_changes = diff_json(base_snapshot, candidate_content)
        server_changes = diff_json(base_snapshot, current_snapshot)
        conflicts, conflicting_paths = _conflict_details(client_changes, server_changes)
        return {
            "document_id": row["id"],
            "project_id": row["project_id"],
            "full_path": row["full_path"],
            "base_version": base_version,
            "current_version": row["current_version"],
            "server_current_version": row["current_version"],
            "schema_id": row["schema_id"],
            "content_source": content_source,
            "base_content": base_snapshot,
            "base_content_text": _json_pretty_dumps(base_snapshot),
            "current_content": current_snapshot,
            "current_content_text": _json_pretty_dumps(current_snapshot),
            "candidate_content": candidate_content,
            "candidate_content_text": _json_pretty_dumps(candidate_content),
            "client_changes": client_changes,
            "server_changes": server_changes,
            "client_generated_patch": _diff_changes_to_patch(client_changes),
            "server_generated_patch": _diff_changes_to_patch(server_changes),
            "conflicting_paths": conflicting_paths,
            "conflicts": conflicts,
            "has_conflicts": bool(conflicts),
            "latest_event": _latest_event_for_conflict(conn, row["id"]),
            "validation": validation,
            "persisted": False,
        }


def _auto_merge_document_content_in_transaction(
    conn: sqlite3.Connection,
    *,
    actor_id: str,
    row: sqlite3.Row,
    base_version: int,
    content: Any = None,
    content_text: str | None = None,
    content_provided: bool | None = None,
    content_text_provided: bool | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    _ensure_preview_base_version(row, base_version)
    current_snapshot = _load_document_snapshot(row)
    events = _events_for_replay(conn, row["id"])
    base_snapshot = replay_events(events, target_version=base_version)
    replayed_current_snapshot = replay_events(events, target_version=row["current_version"])
    if replayed_current_snapshot != current_snapshot:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Event replay does not match latest snapshot.",
            {
                "document_id": row["id"],
                "project_id": row["project_id"],
                "full_path": row["full_path"],
                "current_version": row["current_version"],
            },
        )
    candidate_content, content_source = _resolve_candidate_content(
        content=content,
        content_text=content_text,
        content_provided=content_provided,
        content_text_provided=content_text_provided,
    )
    candidate_content = _ensure_canonical_document(candidate_content)
    client_changes = diff_json(base_snapshot, candidate_content)
    server_changes = diff_json(base_snapshot, current_snapshot)
    conflicts, conflicting_paths = _conflict_details(client_changes, server_changes)
    if conflicts:
        _raise_auto_merge_conflict(
            conn,
            row,
            base_version=base_version,
            conflicts=conflicts,
            conflicting_paths=conflicting_paths,
        )
    array_paths = sorted(
        set(
            _array_sensitive_change_paths(
                client_changes,
                base_snapshot=base_snapshot,
                current_snapshot=current_snapshot,
                candidate_snapshot=candidate_content,
            )
            + _array_sensitive_change_paths(
                server_changes,
                base_snapshot=base_snapshot,
                current_snapshot=current_snapshot,
                candidate_snapshot=candidate_content,
            )
        )
    )
    if array_paths:
        _raise_auto_merge_conflict(
            conn,
            row,
            base_version=base_version,
            conflicts=[],
            conflicting_paths=array_paths,
            array_paths=array_paths,
        )
    client_patch = _diff_changes_to_patch(client_changes)
    try:
        merged = apply_patch(current_snapshot, client_patch).document
    except (UnsupportedPatchOperationError, PatchApplyError) as exc:
        raise AppError(
            ErrorCode.PATCH_APPLY_FAILED,
            "Auto-merge patch could not be applied.",
            {"message": str(exc)},
        ) from exc
    merge_patch = _diff_changes_to_patch(diff_json(current_snapshot, merged))
    response = apply_document_patch_in_transaction(
        conn,
        actor_id=actor_id,
        row=row,
        base_version=row["current_version"],
        patch=merge_patch,
        reason=reason,
    )
    response["content_source"] = content_source
    response["generated_patch"] = merge_patch
    response["merge_strategy"] = "auto"
    response["auto_merged"] = True
    response["client_base_version"] = base_version
    response["server_base_version"] = row["current_version"]
    response["client_changes"] = client_changes
    response["server_changes"] = server_changes
    return response


def update_document_content(
    db_path: str,
    *,
    document_id: str,
    actor_id: str,
    base_version: int,
    content: Any = None,
    content_text: str | None = None,
    content_provided: bool | None = None,
    content_text_provided: bool | None = None,
    reason: str | None = None,
    merge_strategy: str | None = None,
) -> dict[str, Any]:
    normalized_merge_strategy = (merge_strategy or "reject").strip().lower()
    if normalized_merge_strategy not in {"reject", "auto"}:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "merge_strategy must be either reject or auto.",
            {"merge_strategy": merge_strategy, "allowed": ["reject", "auto"]},
        )
    with connect(db_path) as conn:
        # Full-content editor saves are converted to JSON Patch and then use the
        # same event insert + snapshot update transaction as normal patch saves.
        conn.execute("BEGIN IMMEDIATE")
        row = _active_document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_WRITE,
        )
        if base_version != row["current_version"] and normalized_merge_strategy == "auto":
            return _auto_merge_document_content_in_transaction(
                conn,
                actor_id=actor_id,
                row=row,
                base_version=base_version,
                content=content,
                content_text=content_text,
                content_provided=content_provided,
                content_text_provided=content_text_provided,
                reason=reason,
            )
        _check_base_version(conn, row, base_version)
        current_snapshot = _load_document_snapshot(row)
        candidate_content, content_source = _resolve_candidate_content(
            content=content,
            content_text=content_text,
            content_provided=content_provided,
            content_text_provided=content_text_provided,
        )
        _, generated_patch = _generate_patch_for_candidate_content(current_snapshot, candidate_content)
        response = apply_document_patch_in_transaction(
            conn,
            actor_id=actor_id,
            row=row,
            base_version=base_version,
            patch=generated_patch,
            reason=reason,
        )
        response["content_source"] = content_source
        response["generated_patch"] = generated_patch
        response["merge_strategy"] = normalized_merge_strategy
        response["auto_merged"] = False
        return response


def apply_document_patch_in_transaction(
    conn: sqlite3.Connection,
    *,
    actor_id: str,
    row: sqlite3.Row,
    base_version: int,
    patch: list[dict[str, Any]],
    reason: str | None = None,
) -> dict[str, Any]:
    _check_base_version(conn, row, base_version)
    current_snapshot = _load_document_snapshot(row)
    try:
        patch_result = apply_patch(current_snapshot, patch)
    except UnsupportedPatchOperationError as exc:
        raise AppError(
            ErrorCode.UNSUPPORTED_PATCH_OPERATION,
            "Patch operation is not supported in TASK_001.",
            {"message": str(exc), "supported_operations": ["add", "replace", "remove"]},
        ) from exc
    except PatchApplyError as exc:
        raise AppError(
            ErrorCode.PATCH_APPLY_FAILED,
            "Patch could not be applied.",
            {"message": str(exc)},
        ) from exc
    next_snapshot = _ensure_canonical_document(patch_result.document)
    _ensure_patch_changes_snapshot(current_snapshot, next_snapshot)
    validation = {"valid": True, "errors": [], "warnings": []}
    if row["schema_id"]:
        validation = ensure_schema_validates(load_valid_bound_schema_json(conn, row["schema_id"]), next_snapshot)
    ensure_project_usage_allows_snapshot(
        conn,
        project_id=row["project_id"],
        candidate_snapshot=next_snapshot,
        replacing_document_id=row["id"],
    )
    result_version = base_version + 1
    event_id = _insert_event(
        conn,
        document_id=row["id"],
        actor_id=actor_id,
        validation_schema_id=row["schema_id"],
        event_type="update",
        base_version=base_version,
        result_version=result_version,
        patch=patch,
        inverse_patch=patch_result.inverse_patch,
        changed_paths=patch_result.changed_paths,
        before_values=patch_result.before_values,
        after_values=patch_result.after_values,
        summary=f"Updated {len(patch_result.changed_paths)} path(s)",
        reason=reason,
    )
    _update_current_snapshot(conn, document_id=row["id"], snapshot=next_snapshot, version=result_version)
    updated = _active_document_row(conn, row["id"])
    response = _row_to_document(updated)
    response["previous_version"] = base_version
    response["event_id"] = event_id
    response["event_type"] = "update"
    response["validation"] = validation
    response["changed_paths"] = patch_result.changed_paths
    return response


def validate_document_patch_candidate(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    base_version: int,
    patch: list[dict[str, Any]],
) -> dict[str, Any]:
    _check_base_version(conn, row, base_version)
    current_snapshot = _load_document_snapshot(row)
    try:
        patch_result = apply_patch(current_snapshot, patch)
    except UnsupportedPatchOperationError as exc:
        raise AppError(
            ErrorCode.UNSUPPORTED_PATCH_OPERATION,
            "Patch operation is not supported in TASK_001.",
            {"message": str(exc), "supported_operations": ["add", "replace", "remove"]},
        ) from exc
    except PatchApplyError as exc:
        raise AppError(
            ErrorCode.PATCH_APPLY_FAILED,
            "Patch could not be applied.",
            {"message": str(exc)},
        ) from exc
    next_snapshot = _ensure_canonical_document(patch_result.document)
    _ensure_patch_changes_snapshot(current_snapshot, next_snapshot)
    validation = {"valid": True, "errors": [], "warnings": []}
    if row["schema_id"]:
        validation = ensure_schema_validates(load_valid_bound_schema_json(conn, row["schema_id"]), next_snapshot)
    return {
        "candidate_content": next_snapshot,
        "changed_paths": patch_result.changed_paths,
        "inverse_patch": patch_result.inverse_patch,
        "before_values": patch_result.before_values,
        "after_values": patch_result.after_values,
        "validation": validation,
    }


def delete_document(
    db_path: str,
    *,
    document_id: str,
    actor_id: str,
    base_version: int,
    reason: str | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        # The delete event and deleted_at marker are committed or rolled back together.
        conn.execute("BEGIN IMMEDIATE")
        row = _active_document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_DELETE,
        )
        _check_base_version(conn, row, base_version)
        snapshot = _load_document_snapshot(row)
        result_version = base_version + 1
        deleted_at = utc_now()
        event_id = _insert_event(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            validation_schema_id=None,
            event_type="delete",
            base_version=base_version,
            result_version=result_version,
            patch=[],
            inverse_patch=[],
            changed_paths=[],
            before_values=[{"path": "", "exists": True, "value": snapshot}],
            after_values=[{"path": "", "exists": True, "value": snapshot}],
            summary="Soft deleted document",
            reason=reason,
        )
        _mark_document_deleted(conn, document_id=document_id, version=result_version, deleted_at=deleted_at)
        response = _row_to_document(_document_row_including_deleted(conn, document_id))
        response["previous_version"] = base_version
        response["event_id"] = event_id
        response["event_type"] = "delete"
        return response


def restore_document(
    db_path: str,
    *,
    document_id: str,
    actor_id: str,
    base_version: int,
    reason: str | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        # Restore event and deleted_at reset are committed or rolled back together.
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        row = _document_row_including_deleted(conn, document_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=ProjectPermission.DOCUMENT_RESTORE,
        )
        _check_base_version(conn, row, base_version)
        if row["deleted_at"] is None:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "Document is not soft-deleted.",
                {"document_id": document_id},
            )
        path_conflict = conn.execute(
            """
            SELECT id
            FROM json_documents
            WHERE project_id = ?
              AND full_path = ?
              AND deleted_at IS NULL
            LIMIT 1
            """,
            (row["project_id"], row["full_path"]),
        ).fetchone()
        if path_conflict is not None:
            raise AppError(
                ErrorCode.PATCH_APPLY_FAILED,
                "Document path is already used by an active document.",
                {
                    "document_id": document_id,
                    "conflicting_document_id": path_conflict["id"],
                    "project_id": row["project_id"],
                    "full_path": row["full_path"],
                },
            )
        snapshot = _load_document_snapshot(row)
        validation = {"valid": True, "errors": [], "warnings": []}
        if row["schema_id"]:
            validation = ensure_schema_validates(load_valid_bound_schema_json(conn, row["schema_id"]), snapshot)
        ensure_project_usage_allows_snapshot(
            conn,
            project_id=row["project_id"],
            candidate_snapshot=snapshot,
            document_count_delta=1,
        )
        result_version = base_version + 1
        event_id = _insert_event(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            validation_schema_id=row["schema_id"],
            event_type="restore",
            base_version=base_version,
            result_version=result_version,
            patch=[],
            inverse_patch=[],
            changed_paths=[],
            before_values=[{"path": "", "exists": True, "value": snapshot}],
            after_values=[{"path": "", "exists": True, "value": snapshot}],
            summary="Restored document",
            reason=reason,
        )
        _mark_document_restored(conn, document_id=document_id, version=result_version)
        restored = _active_document_row(conn, document_id)
        response = _row_to_document(restored)
        response["previous_version"] = base_version
        response["event_id"] = event_id
        response["event_type"] = "restore"
        response["validation"] = validation
        return response


def get_history(db_path: str, document_id: str, *, actor_id: str | None) -> dict[str, Any]:
    with connect(db_path) as conn:
        _document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        return {
            "document_id": document_id,
            "events": [_row_to_event_with_json_errors(row) for row in _event_rows(conn, document_id)],
        }


def get_document_event_detail(
    db_path: str,
    *,
    document_id: str,
    event_id: str,
    actor_id: str | None,
    include_snapshots: bool = False,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        document = _document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        event_row = conn.execute(
            """
            SELECT *
            FROM document_events
            WHERE id = ? AND document_id = ?
            """,
            (event_id, document_id),
        ).fetchone()
        if event_row is None:
            raise AppError(
                ErrorCode.DOCUMENT_NOT_FOUND,
                "Document event not found for this document.",
                {"document_id": document_id, "event_id": event_id},
            )
        event = _row_to_event_detail(event_row)
        before_snapshot = None
        after_snapshot = None
        snapshot_error = None
        if include_snapshots:
            if event.get("json_errors"):
                snapshot_error = _event_detail_snapshot_error(
                    error_code="EVENT_JSON_DECODE_FAILED",
                    message="Stored document event JSON field is malformed.",
                    details={"failures": event["json_errors"]},
                )
            else:
                try:
                    events = _events_for_replay(conn, document_id)
                    before_snapshot = None
                    if event["base_version"] > 0:
                        before_snapshot = replay_events(events, target_version=event["base_version"])
                    after_snapshot = replay_events(events, target_version=event["result_version"])
                except json.JSONDecodeError as exc:
                    snapshot_error = _event_detail_snapshot_error(
                        error_code="EVENT_JSON_DECODE_FAILED",
                        message="Stored document event JSON field is malformed.",
                        details=_json_decode_details("document_events", exc),
                    )
                except AppError as exc:
                    snapshot_error = _event_detail_snapshot_error(
                        error_code=exc.details.get("diagnostic_code", exc.code),
                        message=exc.message,
                        details=exc.details,
                    )
        snapshots = {
            "included": include_snapshots,
            "before": before_snapshot,
            "after": after_snapshot,
        }
        if snapshot_error:
            snapshots["error"] = snapshot_error
        return {
            "document_id": document_id,
            "project_id": document["project_id"],
            "full_path": document["full_path"],
            "current_version": document["current_version"],
            "deleted_at": document["deleted_at"],
            "event": event,
            "snapshots": snapshots,
        }


def get_document_version(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
    version: int,
) -> dict[str, Any]:
    if version <= 0:
        raise AppError(
            ErrorCode.INVALID_VERSION_RANGE,
            "Document version must be positive.",
            {"version": version},
        )
    with connect(db_path) as conn:
        row = _document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        events = _events_for_replay(conn, document_id)
        content = replay_events(events, target_version=version)
        event = next((event for event in events if event["result_version"] == version), None)
        if event is None:
            raise AppError(
                ErrorCode.DOCUMENT_VERSION_NOT_FOUND,
                "Document version not found.",
                {"target_version": version},
            )
        return {
            "document_id": document_id,
            "project_id": row["project_id"],
            "full_path": row["full_path"],
            "version": version,
            "current_version": row["current_version"],
            "is_latest": version == row["current_version"],
            "deleted_at": row["deleted_at"],
            "content": content,
            "event": event,
        }


def get_document_path_history(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
    path: str,
) -> dict[str, Any]:
    _validate_json_pointer(path)
    with connect(db_path) as conn:
        row = _document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        state: Any = None
        state_exists = False
        changes: list[dict[str, Any]] = []
        replay_error = None
        for event_row in _event_rows(conn, document_id):
            event = _row_to_event_with_json_errors(event_row)
            if event.get("json_errors"):
                replay_error = _event_replay_error(event, event["json_errors"])
                break
            before = _path_value_record(state, path, state_exists=state_exists)
            try:
                state, state_exists = _apply_event_patch_for_history(state, event, state_exists=state_exists)
            except AppError as exc:
                replay_error = _stored_event_replay_error(event, exc)
                break
            after = _path_value_record(state, path, state_exists=state_exists)
            if _records_differ(before, after):
                changes.append(
                    {
                        "event_id": event["id"],
                        "event_type": event["event_type"],
                        "actor_id": event["actor_id"],
                        "base_version": event["base_version"],
                        "result_version": event["result_version"],
                        "changed_paths": event["changed_paths"],
                        "before": before,
                        "after": after,
                        "summary": event["summary"],
                        "reason": event["reason"],
                        "created_at": event["created_at"],
                    }
                )
        if replay_error:
            latest = None
            blame = None
        else:
            latest = _path_value_record(state, path, state_exists=state_exists)
            blame = _path_change_to_blame(changes[-1]) if changes else None
        response = {
            "document_id": document_id,
            "project_id": row["project_id"],
            "full_path": row["full_path"],
            "path": path,
            "current_version": row["current_version"],
            "deleted_at": row["deleted_at"],
            "latest": latest,
            "changes": changes,
            "blame": blame,
        }
        if replay_error:
            response["replay_error"] = replay_error
        return response


def get_document_path_blame(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
    path: str,
) -> dict[str, Any]:
    history = get_document_path_history(
        db_path,
        document_id=document_id,
        actor_id=actor_id,
        path=path,
    )
    response = {
        "document_id": history["document_id"],
        "project_id": history["project_id"],
        "full_path": history["full_path"],
        "path": history["path"],
        "current_version": history["current_version"],
        "deleted_at": history["deleted_at"],
        "latest": history["latest"],
        "blame": history["blame"],
    }
    if "replay_error" in history:
        response["replay_error"] = history["replay_error"]
    return response


def _path_change_to_blame(change: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": change["event_id"],
        "event_type": change["event_type"],
        "actor_id": change["actor_id"],
        "base_version": change["base_version"],
        "result_version": change["result_version"],
        "before": change["before"],
        "after": change["after"],
        "summary": change["summary"],
        "reason": change["reason"],
        "created_at": change["created_at"],
    }


def _events_for_replay(conn: sqlite3.Connection, document_id: str) -> list[dict[str, Any]]:
    events = []
    for row in _event_rows(conn, document_id):
        event = _row_to_event_with_json_errors(row)
        if event.get("json_errors"):
            _raise_malformed_event_json(event)
        events.append(event)
    return events


def reconstruct_document_at_version(db_path: str, document_id: str, version: int) -> Any:
    with connect(db_path) as conn:
        _document_row_including_deleted(conn, document_id)
        events = _events_for_replay(conn, document_id)
        return replay_events(events, target_version=version)


def replay_latest_snapshot(db_path: str, document_id: str) -> Any:
    with connect(db_path) as conn:
        row = _document_row_including_deleted(conn, document_id)
        events = _events_for_replay(conn, document_id)
        replayed = replay_events(events, target_version=row["current_version"])
        return replayed


def assert_replay_matches_latest(db_path: str, document_id: str) -> None:
    with connect(db_path) as conn:
        row = _document_row_including_deleted(conn, document_id)
        expected = _load_document_snapshot(row)
        events = _events_for_replay(conn, document_id)
        actual = replay_events(events, target_version=row["current_version"])
        if actual != expected:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "Event replay does not match latest snapshot.",
                {"document_id": document_id, "current_version": row["current_version"]},
            )


def rollback_document(
    db_path: str,
    *,
    document_id: str,
    actor_id: str,
    base_version: int,
    target_version: int,
    reason: str | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        # Rollback is a normal mutation: new rollback event plus snapshot update in one transaction.
        conn.execute("BEGIN IMMEDIATE")
        row = _active_document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_ROLLBACK,
        )
        _check_base_version(conn, row, base_version)
        if target_version >= base_version:
            raise AppError(
                ErrorCode.INVALID_VERSION_RANGE,
                "Rollback target version must be older than the base version.",
                {"base_version": base_version, "target_version": target_version},
            )
        events = _events_for_replay(conn, document_id)
        target_snapshot = _ensure_canonical_document(replay_events(events, target_version=target_version))
        validation = {"valid": True, "errors": [], "warnings": []}
        if row["schema_id"]:
            validation = ensure_schema_validates(load_valid_bound_schema_json(conn, row["schema_id"]), target_snapshot)
        ensure_project_usage_allows_snapshot(
            conn,
            project_id=row["project_id"],
            candidate_snapshot=target_snapshot,
            replacing_document_id=document_id,
        )
        current_snapshot = _load_document_snapshot(row)
        changes = diff_json(current_snapshot, target_snapshot)
        result_version = base_version + 1
        patch = [{"op": "replace", "path": "", "value": target_snapshot}]
        inverse_patch = [{"op": "replace", "path": "", "value": current_snapshot}]
        before_values = [
            {"path": change["path"], "exists": change["change_type"] != "added", "value": change["before"]}
            for change in changes
        ]
        after_values = [
            {"path": change["path"], "exists": change["change_type"] != "removed", "value": change["after"]}
            for change in changes
        ]
        event_id = _insert_event(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            validation_schema_id=row["schema_id"],
            event_type="rollback",
            base_version=base_version,
            result_version=result_version,
            patch=patch,
            inverse_patch=inverse_patch,
            changed_paths=[change["path"] for change in changes],
            before_values=before_values,
            after_values=after_values,
            summary=f"Rolled back to version {target_version}",
            reason=reason,
        )
        _update_current_snapshot(conn, document_id=document_id, snapshot=target_snapshot, version=result_version)
        updated = _active_document_row(conn, document_id)
        response = _row_to_document(updated)
        response["previous_version"] = base_version
        response["event_id"] = event_id
        response["event_type"] = "rollback"
        response["rollback_target_version"] = target_version
        response["changed_paths"] = [change["path"] for change in changes]
        response["validation"] = validation
        return response


def validate_document(db_path: str, document_id: str, *, actor_id: str | None) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = _active_document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_VALIDATE,
        )
        snapshot = _load_document_snapshot(row)
        response_context = {
            "document_id": document_id,
            "project_id": row["project_id"],
            "full_path": row["full_path"],
            "current_version": row["current_version"],
            "deleted_at": row["deleted_at"],
            "schema_id": row["schema_id"],
        }
        return {**response_context, **_document_validation_result(conn, row, snapshot)}


def diff_document_versions(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
    from_version: int,
    to_version: int,
) -> dict[str, Any]:
    if from_version <= 0 or to_version <= 0:
        raise AppError(
            ErrorCode.INVALID_VERSION_RANGE,
            "Diff versions must be positive document versions.",
            {"from_version": from_version, "to_version": to_version},
        )
    if from_version > to_version:
        raise AppError(
            ErrorCode.INVALID_VERSION_RANGE,
            "from_version must be less than or equal to to_version.",
            {"from_version": from_version, "to_version": to_version},
        )
    with connect(db_path) as conn:
        _document_row_with_permission(
            conn,
            document_id=document_id,
            actor_id=actor_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        events = _events_for_replay(conn, document_id)
        before = replay_events(events, target_version=from_version)
        after = replay_events(events, target_version=to_version)
        return {
            "document_id": document_id,
            "from_version": from_version,
            "to_version": to_version,
            "changes": diff_json(before, after),
        }
