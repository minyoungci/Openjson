from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.database import connect
from app.errors import AppError, ErrorCode
from app.permissions import ProjectPermission, require_actor, require_project_permission
from app.schema_service import get_schema_row, invalid_schema_json_details, safe_load_schema_json
from app.schema_validation import check_json_schema, validate_instance


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


def _malformed_snapshot_validation(error: json.JSONDecodeError) -> dict[str, Any]:
    return {
        "valid": False,
        "errors": [
            {
                "path": "",
                "message": "Document current_snapshot_json is malformed.",
                "validator": "json_syntax",
                "expected": "valid JSON",
                "actual": None,
                "details": _json_decode_details("current_snapshot_json", error),
            }
        ],
        "warnings": [],
    }


def _malformed_schema_validation(error: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": False,
        "errors": [
            {
                "path": "",
                "message": "Schema schema_json is malformed.",
                "validator": "schema_json_syntax",
                "expected": "valid JSON Schema",
                "actual": None,
                "details": error,
            }
        ],
        "warnings": [],
    }


def _invalid_schema_validation(error: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": False,
        "errors": [
            {
                "path": "",
                "message": "Schema schema_json is not a valid JSON Schema.",
                "validator": "schema_json_invalid",
                "expected": "valid JSON Schema",
                "actual": None,
                "details": error,
            }
        ],
        "warnings": [],
    }


def _schema_metadata(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "version": row["version"],
        "file_pattern": row["file_pattern"],
        "is_active": bool(row["is_active"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }


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


def _document_usage(
    schema_json: Any,
    row: sqlite3.Row,
    *,
    schema_error: dict[str, Any] | None = None,
    schema_validation_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if schema_error:
        validation = _malformed_schema_validation(schema_error)
    elif schema_validation_error:
        validation = _invalid_schema_validation(schema_validation_error)
    else:
        try:
            snapshot = _json_loads(row["current_snapshot_json"])
        except json.JSONDecodeError as exc:
            validation = _malformed_snapshot_validation(exc)
        else:
            validation = validate_instance(schema_json, snapshot)
    return {
        "document_id": row["id"],
        "project_id": row["project_id"],
        "full_path": row["full_path"],
        "current_version": row["current_version"],
        "deleted_at": row["deleted_at"],
        "validation": validation,
    }


def get_schema_usage(
    db_path: str,
    *,
    schema_id: str,
    actor_id: str | None,
    include_deleted: bool = False,
    only_invalid: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    _ensure_limit_offset(limit, offset)
    with connect(db_path) as conn:
        require_actor(conn, actor_id)
        schema_row = get_schema_row(conn, schema_id)
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=schema_row["project_id"],
            permission=ProjectPermission.DOCUMENT_VALIDATE,
        )
        where = ["schema_id = ?"]
        params: list[Any] = [schema_id]
        if not include_deleted:
            where.append("deleted_at IS NULL")
        rows = conn.execute(
            f"""
            SELECT *
            FROM json_documents
            WHERE {" AND ".join(where)}
            ORDER BY full_path ASC, id ASC
            """,
            params,
        ).fetchall()
        schema_json, schema_error = safe_load_schema_json(schema_row)
        schema_validation_error = None
        if schema_error is None:
            try:
                check_json_schema(schema_json)
            except AppError as exc:
                if exc.code != ErrorCode.INVALID_JSON_SCHEMA:
                    raise
                schema_validation_error = invalid_schema_json_details(schema_row, exc)
        reports = [
            _document_usage(
                schema_json,
                row,
                schema_error=schema_error,
                schema_validation_error=schema_validation_error,
            )
            for row in rows
        ]

    invalid_reports = [report for report in reports if not report["validation"]["valid"]]
    deleted_count = sum(1 for report in reports if report["deleted_at"] is not None)
    documents = invalid_reports if only_invalid else reports
    page = documents[offset : offset + limit]
    schema = _schema_metadata(schema_row)
    response = {
        "schema_id": schema_id,
        "project_id": schema_row["project_id"],
        "schema": schema,
        "status": "valid" if not invalid_reports else "invalid",
        "summary": {
            "bound_documents": len(reports),
            "valid_documents": len(reports) - len(invalid_reports),
            "invalid_documents": len(invalid_reports),
            "deleted_documents": deleted_count,
        },
        "documents": page,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total": len(documents),
            "has_more": offset + len(page) < len(documents),
        },
        "filters": {
            "include_deleted": include_deleted,
            "only_invalid": only_invalid,
        },
    }
    if schema_error or schema_validation_error:
        response["schema_json_error"] = schema_error or schema_validation_error
    return response
