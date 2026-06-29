from __future__ import annotations

import fnmatch
import json
import sqlite3
import uuid
from typing import Any

from app.database import connect, utc_now
from app.errors import AppError, ErrorCode
from app.path_validation import ensure_relative_glob_pattern
from app.permissions import ProjectPermission, require_actor, require_project_permission
from app.schema_validation import check_json_schema


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AppError(
            ErrorCode.INVALID_JSON_SCHEMA,
            "Schema must be valid JSON.",
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


def malformed_schema_json_details(row: sqlite3.Row, error: json.JSONDecodeError) -> dict[str, Any]:
    return {
        "diagnostic_code": "SCHEMA_JSON_DECODE_FAILED",
        "schema_id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "version": row["version"],
        **_json_decode_details("schema_json", error),
    }


def invalid_schema_json_details(row: sqlite3.Row, error: AppError) -> dict[str, Any]:
    return {
        "diagnostic_code": "SCHEMA_JSON_SCHEMA_INVALID",
        "schema_id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "version": row["version"],
        "field": "schema_json",
        "message": error.details.get("message", error.message),
    }


def safe_load_schema_json(row: sqlite3.Row) -> tuple[Any, dict[str, Any] | None]:
    try:
        return _json_loads(row["schema_json"]), None
    except json.JSONDecodeError as exc:
        return None, malformed_schema_json_details(row, exc)


def load_schema_json(row: sqlite3.Row) -> Any:
    schema_json, error = safe_load_schema_json(row)
    if error:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Stored schema_json is malformed.",
            error,
        )
    return schema_json


def load_valid_schema_json(row: sqlite3.Row) -> Any:
    schema_json = load_schema_json(row)
    try:
        check_json_schema(schema_json)
    except AppError as exc:
        if exc.code != ErrorCode.INVALID_JSON_SCHEMA:
            raise
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Stored schema_json is not a valid JSON Schema.",
            invalid_schema_json_details(row, exc),
        ) from exc
    return schema_json


def load_bound_schema_json(conn: sqlite3.Connection, schema_id: str) -> Any:
    return load_schema_json(get_schema_row(conn, schema_id))


def load_valid_bound_schema_json(conn: sqlite3.Connection, schema_id: str) -> Any:
    return load_valid_schema_json(get_schema_row(conn, schema_id))


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _ensure_valid_file_pattern(file_pattern: str | None) -> None:
    ensure_relative_glob_pattern(file_pattern, error_code=ErrorCode.INVALID_JSON_SCHEMA)


def ensure_project(conn: sqlite3.Connection, project_id: str) -> None:
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.PROJECT_NOT_FOUND,
            "Project not found.",
            {"project_id": project_id},
        )


def row_to_schema(row: sqlite3.Row) -> dict[str, Any]:
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
    else:
        try:
            check_json_schema(schema_json)
        except AppError as exc:
            if exc.code != ErrorCode.INVALID_JSON_SCHEMA:
                raise
            schema["schema_json_error"] = invalid_schema_json_details(row, exc)
    return schema


def get_schema_row(conn: sqlite3.Connection, schema_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM schemas WHERE id = ?", (schema_id,)).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.SCHEMA_NOT_FOUND,
            "Schema not found.",
            {"schema_id": schema_id},
        )
    return row


def ensure_schema_active_for_binding(row: sqlite3.Row) -> None:
    if not bool(row["is_active"]):
        raise AppError(
            ErrorCode.SCHEMA_NOT_ACTIVE,
            "Schema is not active and cannot be bound to new documents.",
            {"schema_id": row["id"]},
        )


def create_schema(
    db_path: str,
    *,
    project_id: str,
    actor_id: str,
    name: str,
    version: str,
    schema_json: Any,
    file_pattern: str | None = None,
) -> dict[str, Any]:
    schema_id = _new_id("schema")
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.SCHEMA_CREATE,
        )
        _ensure_valid_file_pattern(file_pattern)
        check_json_schema(schema_json)
        try:
            conn.execute(
                """
                INSERT INTO schemas (
                    id,
                    project_id,
                    name,
                    version,
                    schema_json,
                    file_pattern,
                    is_active,
                    created_by,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    schema_id,
                    project_id,
                    name,
                    version,
                    _json_dumps(schema_json),
                    file_pattern,
                    actor_id,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise AppError(
                ErrorCode.INVALID_JSON_SCHEMA,
                "Schema name and version must be unique within a project.",
                {"project_id": project_id, "name": name, "version": version},
            ) from exc
        return row_to_schema(get_schema_row(conn, schema_id))


def list_project_schemas(db_path: str, project_id: str, *, actor_id: str | None) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.SCHEMA_READ,
        )
        rows = conn.execute(
            """
            SELECT *
            FROM schemas
            WHERE project_id = ?
            ORDER BY name ASC, version ASC, created_at ASC
            """,
            (project_id,),
        ).fetchall()
        return {"project_id": project_id, "schemas": [row_to_schema(row) for row in rows]}


def get_schema(db_path: str, schema_id: str, *, actor_id: str | None) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_actor(conn, actor_id)
        row = get_schema_row(conn, schema_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=row["project_id"],
            permission=ProjectPermission.SCHEMA_READ,
        )
        return row_to_schema(row)


def resolve_schema_for_document(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    full_path: str,
    schema_id: str | None,
) -> sqlite3.Row | None:
    if schema_id:
        row = get_schema_row(conn, schema_id)
        if row["project_id"] != project_id:
            raise AppError(
                ErrorCode.SCHEMA_PROJECT_MISMATCH,
                "Schema belongs to a different project.",
                {"schema_id": schema_id, "schema_project_id": row["project_id"], "document_project_id": project_id},
            )
        ensure_schema_active_for_binding(row)
        return row

    rows = conn.execute(
        """
        SELECT *
        FROM schemas
        WHERE project_id = ?
          AND is_active = 1
          AND file_pattern IS NOT NULL
        ORDER BY name ASC, version ASC, created_at ASC
        """,
        (project_id,),
    ).fetchall()
    matches = [row for row in rows if fnmatch.fnmatchcase(full_path, row["file_pattern"])]
    if not matches:
        return None
    if len(matches) > 1:
        raise AppError(
            ErrorCode.AMBIGUOUS_SCHEMA_MATCH,
            "Multiple active schemas match this document path.",
            {
                "full_path": full_path,
                "schema_ids": [row["id"] for row in matches],
                "file_patterns": [row["file_pattern"] for row in matches],
            },
        )
    return matches[0]
