from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from dataclasses import dataclass, field
from typing import Any

from app.database import connect
from app.document_service import create_document_in_transaction
from app.errors import AppError, ErrorCode
from app.json_pointer import join_pointer
from app.path_validation import ensure_relative_document_path
from app.permissions import ProjectPermission, require_project_permission
from app.schema_service import load_valid_schema_json
from app.schema_validation import validate_instance


MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_JSON_FILES = 500
MAX_JSON_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_JSON_BYTES = 25 * 1024 * 1024


@dataclass
class ImportCandidate:
    path: str
    size_bytes: int
    content: Any | None = None
    valid_json: bool = False
    root_type: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=lambda: {"valid": True, "errors": [], "warnings": []})
    schema_match: dict[str, Any] = field(default_factory=dict)
    schema_id: str | None = None
    references: list[dict[str, Any]] = field(default_factory=list)

    @property
    def can_import(self) -> bool:
        return self.valid_json and not self.errors


def preview_zip_import(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    archive_bytes: bytes,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_WRITE,
        )
        candidates, skipped_files, top_errors = _analyze_zip_archive(
            conn,
            project_id=project_id,
            archive_bytes=archive_bytes,
        )
        return _build_preview_response(
            project_id=project_id,
            candidates=candidates,
            skipped_files=skipped_files,
            top_errors=top_errors,
        )


def apply_zip_import(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    archive_bytes: bytes,
    reason: str | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_WRITE,
        )
        candidates, skipped_files, top_errors = _analyze_zip_archive(
            conn,
            project_id=project_id,
            archive_bytes=archive_bytes,
        )
        preview = _build_preview_response(
            project_id=project_id,
            candidates=candidates,
            skipped_files=skipped_files,
            top_errors=top_errors,
        )
        if not preview["can_apply"]:
            raise AppError(
                ErrorCode.ZIP_IMPORT_PRECHECK_FAILED,
                "ZIP import precheck failed. No documents were imported.",
                {
                    "project_id": project_id,
                    "errors": preview["errors"],
                    "files": [
                        {"path": item["path"], "errors": item["errors"]}
                        for item in preview["files"]
                        if item["errors"]
                    ],
                },
            )

        created_documents = []
        import_reason = reason or "Imported from ZIP archive."
        for candidate in sorted(candidates, key=lambda item: item.path):
            document = create_document_in_transaction(
                conn,
                project_id=project_id,
                actor_id=actor_id or "",
                full_path=candidate.path,
                content=candidate.content,
                schema_id=candidate.schema_id,
                reason=import_reason,
            )
            created_documents.append(
                {
                    "id": document["id"],
                    "full_path": document["full_path"],
                    "current_version": document["current_version"],
                    "schema_id": document["schema_id"],
                    "event_id": document["event_id"],
                    "event_type": document["event_type"],
                }
            )

        return {
            **preview,
            "applied": True,
            "imported_count": len(created_documents),
            "created_documents": created_documents,
        }


def _analyze_zip_archive(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    archive_bytes: bytes,
) -> tuple[list[ImportCandidate], list[dict[str, Any]], list[dict[str, Any]]]:
    candidates, skipped_files = _read_zip_candidates(archive_bytes)
    top_errors: list[dict[str, Any]] = []
    if not candidates:
        top_errors.append(
            {
                "code": "ZIP_IMPORT_EMPTY",
                "message": "ZIP archive does not contain any .json files.",
            }
        )
        return candidates, skipped_files, top_errors
    if len(candidates) > MAX_JSON_FILES:
        top_errors.append(
            {
                "code": "ZIP_IMPORT_TOO_MANY_JSON_FILES",
                "message": "ZIP archive contains too many JSON files for the MVP importer.",
                "details": {"json_file_count": len(candidates), "max_json_files": MAX_JSON_FILES},
            }
        )

    total_json_bytes = sum(candidate.size_bytes for candidate in candidates)
    if total_json_bytes > MAX_TOTAL_JSON_BYTES:
        top_errors.append(
            {
                "code": "ZIP_IMPORT_TOO_LARGE",
                "message": "ZIP archive JSON payload is too large for the MVP importer.",
                "details": {"total_json_bytes": total_json_bytes, "max_total_json_bytes": MAX_TOTAL_JSON_BYTES},
            }
        )

    _mark_duplicate_paths(candidates)
    existing_documents = _active_document_paths(conn, project_id)
    active_schemas = _active_schema_rows(conn, project_id)
    archive_paths = {candidate.path for candidate in candidates}
    for candidate in candidates:
        _mark_existing_document_conflict(candidate, existing_documents)
        _resolve_schema_match(candidate, active_schemas)
        if candidate.content is not None and candidate.schema_id and not candidate.errors:
            _validate_candidate_schema(candidate, active_schemas[candidate.schema_id])
        if candidate.content is not None:
            candidate.references = _detect_references(
                source_path=candidate.path,
                content=candidate.content,
                archive_paths=archive_paths,
                existing_document_paths=set(existing_documents.keys()),
            )
    return candidates, skipped_files, top_errors


def _read_zip_candidates(archive_bytes: bytes) -> tuple[list[ImportCandidate], list[dict[str, Any]]]:
    if not archive_bytes:
        raise AppError(
            ErrorCode.ZIP_IMPORT_INVALID,
            "ZIP archive body is required.",
        )
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise AppError(
            ErrorCode.ZIP_IMPORT_INVALID,
            "ZIP archive is too large for the MVP importer.",
            {"archive_bytes": len(archive_bytes), "max_archive_bytes": MAX_ARCHIVE_BYTES},
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise AppError(
            ErrorCode.ZIP_IMPORT_INVALID,
            "Request body is not a valid ZIP archive.",
        ) from exc

    candidates: list[ImportCandidate] = []
    skipped_files: list[dict[str, Any]] = []
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.flag_bits & 0x1:
                raise AppError(
                    ErrorCode.ZIP_IMPORT_INVALID,
                    "Encrypted ZIP members are not supported.",
                    {"member_name": info.filename},
                )
            path = _normalize_zip_member_path(info.filename)
            if not path.lower().endswith(".json"):
                skipped_files.append({"path": path, "reason": "not_json"})
                continue
            candidate = ImportCandidate(path=path, size_bytes=info.file_size)
            if info.file_size > MAX_JSON_FILE_BYTES:
                candidate.errors.append(
                    {
                        "code": "JSON_FILE_TOO_LARGE",
                        "message": "JSON file exceeds the per-file import limit.",
                        "details": {"size_bytes": info.file_size, "max_json_file_bytes": MAX_JSON_FILE_BYTES},
                    }
                )
                candidates.append(candidate)
                continue
            try:
                raw = archive.read(info)
            except (RuntimeError, zipfile.BadZipFile) as exc:
                raise AppError(
                    ErrorCode.ZIP_IMPORT_INVALID,
                    "ZIP member could not be read.",
                    {"member_name": info.filename, "message": str(exc)},
                ) from exc
            _parse_candidate_json(candidate, raw)
            candidates.append(candidate)
    return candidates, skipped_files


def _normalize_zip_member_path(member_name: str) -> str:
    path = member_name.replace("\\", "/")
    if path.startswith("/") or (len(path) >= 2 and path[1] == ":" and path[0].isalpha()):
        raise AppError(
            ErrorCode.ZIP_IMPORT_INVALID,
            "ZIP member path must be relative.",
            {"member_name": member_name},
        )
    try:
        return ensure_relative_document_path(
            path,
            error_code=ErrorCode.ZIP_IMPORT_INVALID,
            subject="ZIP member path",
        )
    except AppError as exc:
        exc.details = {**exc.details, "member_name": member_name}
        raise


def _parse_candidate_json(candidate: ImportCandidate, raw: bytes) -> None:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        candidate.errors.append(
            {
                "code": ErrorCode.INVALID_JSON_SYNTAX,
                "message": "JSON file must be UTF-8 encoded.",
                "details": {"message": str(exc)},
            }
        )
        return
    try:
        content = json.loads(text, parse_constant=_reject_json_constant)
    except ValueError as exc:
        details: dict[str, Any] = {"message": str(exc)}
        if isinstance(exc, json.JSONDecodeError):
            details.update({"line": exc.lineno, "column": exc.colno, "position": exc.pos})
        candidate.errors.append(
            {
                "code": ErrorCode.INVALID_JSON_SYNTAX,
                "message": "JSON file is malformed.",
                "details": details,
            }
        )
        return
    candidate.valid_json = True
    candidate.content = content
    candidate.root_type = _json_root_type(content)
    if not isinstance(content, (dict, list)):
        candidate.errors.append(
            {
                "code": ErrorCode.INVALID_JSON_SYNTAX,
                "message": "JSON document content must be an object or array.",
                "details": {"actual_type": candidate.root_type},
            }
        )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"{value} is not valid JSON.")


def _json_root_type(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _mark_duplicate_paths(candidates: list[ImportCandidate]) -> None:
    by_path: dict[str, list[ImportCandidate]] = {}
    for candidate in candidates:
        by_path.setdefault(candidate.path, []).append(candidate)
    for path, duplicates in by_path.items():
        if len(duplicates) <= 1:
            continue
        error = {
            "code": "DUPLICATE_ARCHIVE_PATH",
            "message": "ZIP archive contains duplicate JSON member paths.",
            "details": {"full_path": path, "count": len(duplicates)},
        }
        for candidate in duplicates:
            candidate.errors.append(error)


def _active_document_paths(conn: sqlite3.Connection, project_id: str) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT id, full_path
        FROM json_documents
        WHERE project_id = ?
          AND deleted_at IS NULL
        """,
        (project_id,),
    ).fetchall()
    return {row["full_path"]: row["id"] for row in rows}


def _mark_existing_document_conflict(candidate: ImportCandidate, existing_documents: dict[str, str]) -> None:
    existing_document_id = existing_documents.get(candidate.path)
    if existing_document_id is None:
        return
    candidate.errors.append(
        {
            "code": "DOCUMENT_PATH_CONFLICT",
            "message": "An active document already exists at this full_path.",
            "details": {"full_path": candidate.path, "document_id": existing_document_id},
        }
    )


def _active_schema_rows(conn: sqlite3.Connection, project_id: str) -> dict[str, sqlite3.Row]:
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
    return {row["id"]: row for row in rows}


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


def _resolve_schema_match(candidate: ImportCandidate, active_schemas: dict[str, sqlite3.Row]) -> None:
    import fnmatch

    matches = [
        row
        for row in active_schemas.values()
        if fnmatch.fnmatchcase(candidate.path, row["file_pattern"])
    ]
    match_metadata = [_schema_metadata(row) for row in matches]
    if not matches:
        candidate.schema_match = {"status": "no_match", "schema_id": None, "matches": []}
        return
    if len(matches) == 1:
        candidate.schema_id = matches[0]["id"]
        candidate.schema_match = {
            "status": "matched",
            "schema_id": candidate.schema_id,
            "matches": match_metadata,
        }
        return
    candidate.schema_match = {
        "status": "ambiguous",
        "schema_id": None,
        "schema_ids": [row["id"] for row in matches],
        "matches": match_metadata,
    }
    candidate.errors.append(
        {
            "code": ErrorCode.AMBIGUOUS_SCHEMA_MATCH,
            "message": "Multiple active schemas match this document path.",
            "details": {
                "full_path": candidate.path,
                "schema_ids": [row["id"] for row in matches],
                "file_patterns": [row["file_pattern"] for row in matches],
            },
        }
    )


def _validate_candidate_schema(candidate: ImportCandidate, schema_row: sqlite3.Row) -> None:
    result = validate_instance(load_valid_schema_json(schema_row), candidate.content)
    candidate.validation = result
    if result["valid"]:
        return
    candidate.errors.append(
        {
            "code": ErrorCode.SCHEMA_VALIDATION_FAILED,
            "message": "Document failed schema validation.",
            "details": {"errors": result["errors"]},
        }
    )


def _detect_references(
    *,
    source_path: str,
    content: Any,
    archive_paths: set[str],
    existing_document_paths: set[str],
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []

    def visit(value: Any, pointer: str, key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, join_pointer(pointer, str(child_key)), str(child_key))
            return
        if isinstance(value, list):
            for index, child_value in enumerate(value):
                visit(child_value, join_pointer(pointer, str(index)), key=None)
            return
        if not isinstance(value, str):
            return
        kind = "json_schema_ref" if key == "$ref" else "json_path_string"
        if key != "$ref" and not _looks_like_json_file_reference(value):
            return
        target_path, resolution_error = _resolve_reference_target(source_path, value)
        if target_path is None:
            if resolution_error in {"local_fragment", "external_reference"}:
                return
            references.append(
                {
                    "source_path": source_path,
                    "source_pointer": pointer,
                    "kind": kind,
                    "value": value,
                    "target_path": None,
                    "target_status": "missing",
                    "resolution_error": resolution_error,
                }
            )
            return
        if target_path in archive_paths:
            target_status = "in_archive"
        elif target_path in existing_document_paths:
            target_status = "existing_document"
        else:
            target_status = "missing"
        references.append(
            {
                "source_path": source_path,
                "source_pointer": pointer,
                "kind": kind,
                "value": value,
                "target_path": target_path,
                "target_status": target_status,
            }
        )

    visit(content, "")
    references.sort(key=lambda item: (item["source_pointer"], item.get("target_path") or "", item["value"]))
    return references


def _looks_like_json_file_reference(value: str) -> bool:
    target = value.split("#", 1)[0]
    return target.lower().endswith(".json")


def _resolve_reference_target(source_path: str, value: str) -> tuple[str | None, str | None]:
    raw_target = value.split("#", 1)[0]
    if not raw_target or raw_target.startswith("#"):
        return None, "local_fragment"
    if "://" in raw_target or raw_target.startswith("urn:") or raw_target.startswith("data:"):
        return None, "external_reference"
    if raw_target.startswith("/"):
        joined = raw_target.lstrip("/")
    else:
        source_dir = source_path.rsplit("/", 1)[0] if "/" in source_path else ""
        joined = f"{source_dir}/{raw_target}" if source_dir else raw_target
    normalized = _normalize_relative_reference_path(joined)
    if normalized is None:
        return None, "reference_path_escapes_project"
    try:
        return ensure_relative_document_path(
            normalized,
            error_code=ErrorCode.INVALID_REQUEST,
            subject="reference target path",
        ), None
    except AppError as exc:
        return None, exc.message


def _normalize_relative_reference_path(path: str) -> str | None:
    parts: list[str] = []
    for raw_part in path.replace("\\", "/").split("/"):
        if raw_part in {"", "."}:
            continue
        if raw_part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(raw_part)
    return "/".join(parts)


def _build_preview_response(
    *,
    project_id: str,
    candidates: list[ImportCandidate],
    skipped_files: list[dict[str, Any]],
    top_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    files = [_candidate_response(candidate) for candidate in sorted(candidates, key=lambda item: item.path)]
    edges = [reference for candidate in candidates for reference in candidate.references]
    edges.sort(key=lambda item: (item["source_path"], item["source_pointer"], item.get("target_path") or ""))
    missing = [edge for edge in edges if edge["target_status"] == "missing"]
    can_apply = not top_errors and bool(candidates) and all(candidate.can_import for candidate in candidates)
    return {
        "project_id": project_id,
        "archive": {
            "json_file_count": len(candidates),
            "skipped_file_count": len(skipped_files),
            "total_json_bytes": sum(candidate.size_bytes for candidate in candidates),
            "limits": {
                "max_archive_bytes": MAX_ARCHIVE_BYTES,
                "max_json_files": MAX_JSON_FILES,
                "max_json_file_bytes": MAX_JSON_FILE_BYTES,
                "max_total_json_bytes": MAX_TOTAL_JSON_BYTES,
            },
        },
        "can_apply": can_apply,
        "errors": top_errors,
        "folders": _folder_summary(candidates),
        "files": files,
        "skipped_files": skipped_files,
        "references": {
            "summary": {
                "edge_count": len(edges),
                "missing_count": len(missing),
            },
            "edges": edges,
            "missing": missing,
        },
    }


def _candidate_response(candidate: ImportCandidate) -> dict[str, Any]:
    return {
        "path": candidate.path,
        "size_bytes": candidate.size_bytes,
        "valid_json": candidate.valid_json,
        "root_type": candidate.root_type,
        "can_import": candidate.can_import,
        "schema_id": candidate.schema_id,
        "schema_match": candidate.schema_match,
        "validation": candidate.validation,
        "references": candidate.references,
        "errors": candidate.errors,
    }


def _folder_summary(candidates: list[ImportCandidate]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        folder = candidate.path.rsplit("/", 1)[0] if "/" in candidate.path else ""
        counts[folder] = counts.get(folder, 0) + 1
    return [
        {"path": folder, "json_file_count": count}
        for folder, count in sorted(counts.items(), key=lambda item: item[0])
    ]
