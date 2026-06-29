from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.database import connect
from app.errors import AppError, ErrorCode
from app.integrity_service import (
    build_document_event_chain_report_from_event_rows,
    build_document_replay_report_from_event_rows,
)
from app.permissions import ProjectPermission, require_project_permission
from app.schema_service import invalid_schema_json_details, safe_load_schema_json
from app.schema_validation import check_json_schema, validate_instance


def _json_loads(value: str) -> Any:
    return json.loads(value)


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


def _unbound_validation() -> dict[str, Any]:
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
                "details": {
                    "field": "current_snapshot_json",
                    "message": error.msg,
                    "line": error.lineno,
                    "column": error.colno,
                    "position": error.pos,
                },
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


def _schema_for_document(conn: sqlite3.Connection, schema_id: str) -> sqlite3.Row:
    return conn.execute(
        """
        SELECT *
        FROM schemas
        WHERE id = ?
        """,
        (schema_id,),
    ).fetchone()


def _document_validation_report(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    event_rows = _document_event_rows(conn, row["id"])
    replay_report = build_document_replay_report_from_event_rows(row, event_rows)
    event_chain_report = build_document_event_chain_report_from_event_rows(row, event_rows)
    try:
        snapshot = _json_loads(row["current_snapshot_json"])
    except json.JSONDecodeError as exc:
        validation = _malformed_snapshot_validation(exc)
    else:
        if row["schema_id"] is None:
            validation = _unbound_validation()
        else:
            schema = _schema_for_document(conn, row["schema_id"])
            schema_json, schema_error = safe_load_schema_json(schema)
            if schema_error:
                validation = _malformed_schema_validation(schema_error)
            else:
                try:
                    check_json_schema(schema_json)
                except AppError as exc:
                    if exc.code != ErrorCode.INVALID_JSON_SCHEMA:
                        raise
                    validation = _invalid_schema_validation(invalid_schema_json_details(schema, exc))
                else:
                    validation = validate_instance(schema_json, snapshot)
    report = {
        "document_id": row["id"],
        "project_id": row["project_id"],
        "full_path": row["full_path"],
        "current_version": row["current_version"],
        "deleted_at": row["deleted_at"],
        "schema_id": row["schema_id"],
        "validation": validation,
        "integrity": {
            "replay_status": replay_report["status"],
            "replay_matches_latest": replay_report["replay_matches_latest"],
            "event_chain_status": event_chain_report["status"],
            "event_chain_failure_count": event_chain_report["failure_count"],
        },
    }
    return report, replay_report, event_chain_report


def _integrity_envelope(
    replay_reports: list[dict[str, Any]],
    event_chain_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    replay_failures = [report for report in replay_reports if report["status"] != "ok"]
    event_chain_failures = [report for report in event_chain_reports if report["status"] != "ok"]
    replay_status = "ok" if not replay_failures else "failed"
    event_chain_status = "ok" if not event_chain_failures else "failed"
    return {
        "status": "ok" if replay_status == "ok" and event_chain_status == "ok" else "failed",
        "replay_consistent": replay_status == "ok",
        "event_chain_consistent": event_chain_status == "ok",
        "checks": {
            "replay": {
                "status": replay_status,
                "checked_documents": len(replay_reports),
                "failure_count": len(replay_failures),
                "documents": replay_reports,
                "failures": replay_failures,
            },
            "event_chain": {
                "status": event_chain_status,
                "checked_documents": len(event_chain_reports),
                "failure_count": len(event_chain_failures),
                "documents": event_chain_reports,
                "failures": event_chain_failures,
            },
        },
    }


def get_project_validation_report(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    include_deleted: bool = False,
    only_invalid: bool = False,
) -> dict[str, Any]:
    where = ["project_id = ?"]
    if not include_deleted:
        where.append("deleted_at IS NULL")
    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_VALIDATE,
        )
        rows = conn.execute(
            f"""
            SELECT *
            FROM json_documents
            WHERE {" AND ".join(where)}
            ORDER BY full_path ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        documents_with_integrity = [_document_validation_report(conn, row) for row in rows]
        reports = [item[0] for item in documents_with_integrity]
        replay_reports = [item[1] for item in documents_with_integrity]
        event_chain_reports = [item[2] for item in documents_with_integrity]
        invalid_reports = [report for report in reports if not report["validation"]["valid"]]
        unbound_count = sum(1 for report in reports if report["schema_id"] is None)
        deleted_count = sum(1 for report in reports if report["deleted_at"] is not None)
        documents = invalid_reports if only_invalid else reports
        return {
            "project_id": project_id,
            "status": "valid" if not invalid_reports else "invalid",
            "include_deleted": include_deleted,
            "only_invalid": only_invalid,
            "summary": {
                "checked_documents": len(reports),
                "valid_documents": len(reports) - len(invalid_reports),
                "invalid_documents": len(invalid_reports),
                "unbound_documents": unbound_count,
                "deleted_documents": deleted_count,
            },
            "integrity": _integrity_envelope(replay_reports, event_chain_reports),
            "documents": documents,
        }
