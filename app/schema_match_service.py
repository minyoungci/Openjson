from __future__ import annotations

import fnmatch
import sqlite3
from typing import Any

from app.database import connect
from app.errors import AppError, ErrorCode
from app.path_validation import ensure_relative_document_path
from app.permissions import ProjectPermission, require_project_permission


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


def _ensure_preview_full_path(full_path: str | None) -> str:
    return ensure_relative_document_path(
        full_path,
        error_code=ErrorCode.INVALID_REQUEST,
        subject="full_path",
    )


def _resolution(matches: list[dict[str, Any]]) -> dict[str, Any]:
    if not matches:
        return {"status": "no_match", "schema_id": None}
    if len(matches) == 1:
        return {"status": "matched", "schema_id": matches[0]["id"]}
    return {"status": "ambiguous", "schema_id": None, "schema_ids": [match["id"] for match in matches]}


def preview_project_schema_matches(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    full_path: str | None,
) -> dict[str, Any]:
    normalized_full_path = _ensure_preview_full_path(full_path)
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
              AND is_active = 1
              AND file_pattern IS NOT NULL
            ORDER BY name ASC, version ASC, created_at ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        matches = [
            _schema_metadata(row)
            for row in rows
            if fnmatch.fnmatchcase(normalized_full_path, row["file_pattern"])
        ]
    return {
        "project_id": project_id,
        "full_path": normalized_full_path,
        "match_count": len(matches),
        "resolution": _resolution(matches),
        "matches": matches,
    }
