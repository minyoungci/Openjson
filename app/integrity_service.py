from __future__ import annotations

import json
from typing import Any

from app.database import connect, get_schema_migration_status
from app.errors import AppError, ErrorCode
from app.json_patch import PatchApplyError, UnsupportedPatchOperationError, apply_patch
from app.permissions import ProjectPermission, require_actor, require_project_permission
from app.replay import diff_json, replay_events


DOCUMENT_EVENT_TYPES = {"create", "update", "delete", "restore", "rollback"}


class PersistedJsonDecodeError(ValueError):
    def __init__(self, field: str, error: json.JSONDecodeError):
        self.field = field
        self.error = error
        super().__init__(f"Stored JSON field {field} is malformed: {error.msg}")


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


def _load_event_json_field(row, field: str) -> Any:
    try:
        return _json_loads(row[field])
    except json.JSONDecodeError as exc:
        raise PersistedJsonDecodeError(field, exc) from exc


def _row_to_event(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "actor_id": row["actor_id"],
        "validation_schema_id": row["validation_schema_id"],
        "event_type": row["event_type"],
        "base_version": row["base_version"],
        "result_version": row["result_version"],
        "patch": _load_event_json_field(row, "patch"),
        "inverse_patch": _load_event_json_field(row, "inverse_patch"),
        "changed_paths": _load_event_json_field(row, "changed_paths"),
        "before_values": _load_event_json_field(row, "before_values"),
        "after_values": _load_event_json_field(row, "after_values"),
        "summary": row["summary"],
        "reason": row["reason"],
        "created_at": row["created_at"],
    }


def _raw_event_json_failure(row, exc: PersistedJsonDecodeError) -> dict[str, Any]:
    return {
        "event_id": row["id"],
        "event_type": row["event_type"],
        "base_version": row["base_version"],
        "result_version": row["result_version"],
        "error_code": "EVENT_JSON_DECODE_FAILED",
        "message": "Stored document event JSON field is malformed.",
        "details": _json_decode_details(exc.field, exc.error),
    }


def _load_event_rows(event_rows) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in event_rows:
        try:
            events.append(_row_to_event(row))
        except PersistedJsonDecodeError as exc:
            failures.append(_raw_event_json_failure(row, exc))
    return events, failures


def _latest_event_version_from_rows(event_rows) -> int | None:
    return max((row["result_version"] for row in event_rows), default=None)


def _event_json_replay_report(document, event_rows, failures: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "document_id": document["id"],
        "project_id": document["project_id"],
        "full_path": document["full_path"],
        "current_version": document["current_version"],
        "latest_event_version": _latest_event_version_from_rows(event_rows),
        "event_count": len(event_rows),
        "deleted_at": document["deleted_at"],
        "status": "failed",
        "replay_matches_latest": False,
        "error_code": "EVENT_JSON_DECODE_FAILED",
        "message": "One or more stored document event JSON fields are malformed.",
        "details": {"failures": failures},
    }


def _event_json_chain_report(document, event_rows, failures: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "document_id": document["id"],
        "project_id": document["project_id"],
        "full_path": document["full_path"],
        "current_version": document["current_version"],
        "latest_event_version": _latest_event_version_from_rows(event_rows),
        "event_count": len(event_rows),
        "checked_events": 0,
        "deleted_at": document["deleted_at"],
        "status": "failed",
        "checks": {
            "version_chain": "failed",
            "event_types": "failed",
            "event_metadata": "failed",
            "replay_matches_latest": "failed",
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def _replay_report_from_rows(document, event_rows) -> dict[str, Any]:
    events, parse_failures = _load_event_rows(event_rows)
    if parse_failures:
        return _event_json_replay_report(document, event_rows, parse_failures)
    return _document_integrity_report(document, events)


def _event_chain_report_from_rows(document, event_rows) -> dict[str, Any]:
    events, parse_failures = _load_event_rows(event_rows)
    if parse_failures:
        return _event_json_chain_report(document, event_rows, parse_failures)
    return _document_event_chain_report(document, events)


def _document_integrity_report(document, events: list[dict[str, Any]]) -> dict[str, Any]:
    latest_event_version = max((event["result_version"] for event in events), default=None)
    base = {
        "document_id": document["id"],
        "project_id": document["project_id"],
        "full_path": document["full_path"],
        "current_version": document["current_version"],
        "latest_event_version": latest_event_version,
        "event_count": len(events),
        "deleted_at": document["deleted_at"],
    }
    if latest_event_version != document["current_version"]:
        return {
            **base,
            "status": "failed",
            "replay_matches_latest": False,
            "error_code": "VERSION_MISMATCH",
            "message": "Document current_version does not match latest event result_version.",
        }
    try:
        replayed = replay_events(events, target_version=document["current_version"])
    except AppError as exc:
        return {
            **base,
            "status": "failed",
            "replay_matches_latest": False,
            "error_code": exc.code,
            "message": exc.message,
            "details": exc.details,
        }
    try:
        expected = _json_loads(document["current_snapshot_json"])
    except json.JSONDecodeError as exc:
        return {
            **base,
            "status": "failed",
            "replay_matches_latest": False,
            "error_code": "SNAPSHOT_JSON_DECODE_FAILED",
            "message": "Document current_snapshot_json is malformed.",
            "details": _json_decode_details("current_snapshot_json", exc),
        }
    if replayed != expected:
        return {
            **base,
            "status": "failed",
            "replay_matches_latest": False,
            "error_code": "SNAPSHOT_REPLAY_MISMATCH",
            "message": "Replayed event log does not match current snapshot.",
        }
    return {
        **base,
        "status": "ok",
        "replay_matches_latest": True,
    }


def build_document_replay_report(document, events: list[dict[str, Any]]) -> dict[str, Any]:
    return _document_integrity_report(document, events)


def build_document_replay_report_from_event_rows(document, event_rows) -> dict[str, Any]:
    return _replay_report_from_rows(document, event_rows)


def _root_value_record(state: Any) -> dict[str, Any]:
    return {"path": "", "exists": state is not None, "value": state}


def _new_event_chain_failure(
    *,
    event: dict[str, Any] | None,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failure: dict[str, Any] = {
        "event_id": event["id"] if event else None,
        "event_type": event["event_type"] if event else None,
        "base_version": event["base_version"] if event else None,
        "result_version": event["result_version"] if event else None,
        "error_code": error_code,
        "message": message,
    }
    if details:
        failure["details"] = details
    return failure


def _check_expected_field(
    failures: list[dict[str, Any]],
    *,
    event: dict[str, Any],
    field: str,
    expected: Any,
) -> None:
    actual = event[field]
    if actual != expected:
        failures.append(
            _new_event_chain_failure(
                event=event,
                error_code=f"EVENT_{field.upper()}_MISMATCH",
                message=f"Stored event {field} does not match replay-observed metadata.",
                details={"expected": expected, "actual": actual},
            )
        )


def _document_event_chain_report(document, events: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    state: Any = None
    previous_version = 0
    checks = {
        "version_chain": "ok",
        "event_types": "ok",
        "event_metadata": "ok",
        "replay_matches_latest": "ok",
    }
    if not events:
        failures.append(
            _new_event_chain_failure(
                event=None,
                error_code="EVENT_CHAIN_EMPTY",
                message="Document has no events.",
            )
        )
        checks["version_chain"] = "failed"

    for index, event in enumerate(events):
        expected_base_version = previous_version
        expected_result_version = previous_version + 1
        if event["base_version"] != expected_base_version:
            checks["version_chain"] = "failed"
            failures.append(
                _new_event_chain_failure(
                    event=event,
                    error_code="EVENT_BASE_VERSION_MISMATCH",
                    message="Event base_version does not continue from the previous event.",
                    details={"expected_base_version": expected_base_version, "actual_base_version": event["base_version"]},
                )
            )
        if event["result_version"] != expected_result_version:
            checks["version_chain"] = "failed"
            failures.append(
                _new_event_chain_failure(
                    event=event,
                    error_code="EVENT_RESULT_VERSION_MISMATCH",
                    message="Event result_version is not the next contiguous document version.",
                    details={
                        "expected_result_version": expected_result_version,
                        "actual_result_version": event["result_version"],
                    },
                )
            )
        if index == 0 and event["event_type"] != "create":
            checks["event_types"] = "failed"
            failures.append(
                _new_event_chain_failure(
                    event=event,
                    error_code="EVENT_FIRST_TYPE_MISMATCH",
                    message="First document event must be a create event.",
                )
            )
        if event["event_type"] not in DOCUMENT_EVENT_TYPES:
            checks["event_types"] = "failed"
            failures.append(
                _new_event_chain_failure(
                    event=event,
                    error_code="EVENT_TYPE_UNSUPPORTED",
                    message="Event type is not one of the supported document mutation event types.",
                    details={"allowed_event_types": sorted(DOCUMENT_EVENT_TYPES), "actual_event_type": event["event_type"]},
                )
            )

        try:
            if (
                index == 0
                and event["event_type"] == "create"
                and len(event["patch"]) == 1
                and event["patch"][0].get("op") == "add"
                and event["patch"][0].get("path") == ""
                and "value" in event["patch"][0]
            ):
                next_state = event["patch"][0]["value"]
                expected_changed_paths = [""]
                expected_inverse_patch = [{"op": "remove", "path": ""}]
                expected_before_values = [{"path": "", "exists": False, "value": None}]
                expected_after_values = [{"path": "", "exists": True, "value": next_state}]
            elif (
                event["event_type"] == "rollback"
                and len(event["patch"]) == 1
                and event["patch"][0].get("op") == "replace"
                and event["patch"][0].get("path") == ""
                and "value" in event["patch"][0]
            ):
                next_state = event["patch"][0]["value"]
                changes = diff_json(state, next_state)
                expected_changed_paths = [change["path"] for change in changes]
                expected_inverse_patch = [{"op": "replace", "path": "", "value": state}]
                expected_before_values = [
                    {"path": change["path"], "exists": change["change_type"] != "added", "value": change["before"]}
                    for change in changes
                ]
                expected_after_values = [
                    {"path": change["path"], "exists": change["change_type"] != "removed", "value": change["after"]}
                    for change in changes
                ]
            elif event["patch"]:
                patch_result = apply_patch(state, event["patch"])
                next_state = patch_result.document
                expected_changed_paths = patch_result.changed_paths
                expected_inverse_patch = patch_result.inverse_patch
                expected_before_values = patch_result.before_values
                expected_after_values = patch_result.after_values
            else:
                next_state = state
                root_record = _root_value_record(state)
                expected_changed_paths = []
                expected_inverse_patch = []
                expected_before_values = [root_record]
                expected_after_values = [root_record]
        except UnsupportedPatchOperationError as exc:
            checks["event_metadata"] = "failed"
            failures.append(
                _new_event_chain_failure(
                    event=event,
                    error_code="EVENT_PATCH_UNSUPPORTED",
                    message="Stored event patch contains an unsupported operation.",
                    details={"message": str(exc)},
                )
            )
            next_state = state
            expected_changed_paths = []
            expected_inverse_patch = []
            expected_before_values = []
            expected_after_values = []
        except PatchApplyError as exc:
            checks["event_metadata"] = "failed"
            failures.append(
                _new_event_chain_failure(
                    event=event,
                    error_code="EVENT_PATCH_APPLY_FAILED",
                    message="Stored event patch could not be applied while checking the event chain.",
                    details={"message": str(exc)},
                )
            )
            next_state = state
            expected_changed_paths = []
            expected_inverse_patch = []
            expected_before_values = []
            expected_after_values = []

        before_failure_count = len(failures)
        _check_expected_field(failures, event=event, field="changed_paths", expected=expected_changed_paths)
        _check_expected_field(failures, event=event, field="inverse_patch", expected=expected_inverse_patch)
        _check_expected_field(failures, event=event, field="before_values", expected=expected_before_values)
        _check_expected_field(failures, event=event, field="after_values", expected=expected_after_values)
        if len(failures) != before_failure_count:
            checks["event_metadata"] = "failed"

        state = next_state
        previous_version = event["result_version"]

    try:
        expected_snapshot = _json_loads(document["current_snapshot_json"])
    except json.JSONDecodeError as exc:
        checks["replay_matches_latest"] = "failed"
        failures.append(
            _new_event_chain_failure(
                event=events[-1] if events else None,
                error_code="SNAPSHOT_JSON_DECODE_FAILED",
                message="Document current_snapshot_json is malformed.",
                details=_json_decode_details("current_snapshot_json", exc),
            )
        )
    else:
        if state != expected_snapshot:
            checks["replay_matches_latest"] = "failed"
            failures.append(
                _new_event_chain_failure(
                    event=events[-1] if events else None,
                    error_code="EVENT_CHAIN_REPLAY_MISMATCH",
                    message="Event-chain replay result does not match current snapshot.",
                )
            )
    latest_event_version = max((event["result_version"] for event in events), default=None)
    if latest_event_version != document["current_version"]:
        checks["version_chain"] = "failed"
        failures.append(
            _new_event_chain_failure(
                event=events[-1] if events else None,
                error_code="EVENT_CHAIN_CURRENT_VERSION_MISMATCH",
                message="Document current_version does not match the latest event result_version.",
                details={
                    "current_version": document["current_version"],
                    "latest_event_version": latest_event_version,
                },
            )
        )

    return {
        "document_id": document["id"],
        "project_id": document["project_id"],
        "full_path": document["full_path"],
        "current_version": document["current_version"],
        "latest_event_version": latest_event_version,
        "event_count": len(events),
        "checked_events": len(events),
        "deleted_at": document["deleted_at"],
        "status": "ok" if not failures else "failed",
        "checks": checks,
        "failure_count": len(failures),
        "failures": failures,
    }


def build_document_event_chain_report(document, events: list[dict[str, Any]]) -> dict[str, Any]:
    return _document_event_chain_report(document, events)


def build_document_event_chain_report_from_event_rows(document, event_rows) -> dict[str, Any]:
    return _event_chain_report_from_rows(document, event_rows)


def check_replay_consistency(db_path: str) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    checked_documents = 0
    with connect(db_path) as conn:
        documents = conn.execute(
            """
            SELECT *
            FROM json_documents
            ORDER BY project_id ASC, full_path ASC, id ASC
            """
        ).fetchall()
        for document in documents:
            checked_documents += 1
            event_rows = conn.execute(
                """
                SELECT *
                FROM document_events
                WHERE document_id = ?
                ORDER BY result_version ASC
                """,
                (document["id"],),
            ).fetchall()
            report = _replay_report_from_rows(document, event_rows)
            if report["status"] != "ok":
                failures.append(
                    {
                        key: value
                        for key, value in report.items()
                        if key not in {"status", "event_count", "deleted_at", "replay_matches_latest"}
                    }
                )
    return {
        "status": "ok" if not failures else "failed",
        "checked_documents": checked_documents,
        "failure_count": len(failures),
        "failures": failures,
    }


def check_event_chain_consistency(db_path: str) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    checked_documents = 0
    with connect(db_path) as conn:
        documents = conn.execute(
            """
            SELECT *
            FROM json_documents
            ORDER BY project_id ASC, full_path ASC, id ASC
            """
        ).fetchall()
        for document in documents:
            checked_documents += 1
            event_rows = conn.execute(
                """
                SELECT *
                FROM document_events
                WHERE document_id = ?
                ORDER BY result_version ASC, id ASC
                """,
                (document["id"],),
            ).fetchall()
            report = _event_chain_report_from_rows(document, event_rows)
            if report["status"] != "ok":
                failures.append(report)
    return {
        "status": "ok" if not failures else "failed",
        "checked_documents": checked_documents,
        "failure_count": len(failures),
        "failures": failures,
    }


def check_sqlite_integrity(db_path: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        foreign_key_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()

    foreign_key_failures = [
        {
            "table": row[0],
            "rowid": row[1],
            "parent": row[2],
            "fkid": row[3],
        }
        for row in foreign_key_rows
    ]
    integrity_messages = [row[0] for row in integrity_rows]
    integrity_ok = integrity_messages == ["ok"]
    return {
        "status": "ok" if not foreign_key_failures and integrity_ok else "failed",
        "foreign_key_check": {
            "status": "ok" if not foreign_key_failures else "failed",
            "failure_count": len(foreign_key_failures),
            "failures": foreign_key_failures,
        },
        "integrity_check": {
            "status": "ok" if integrity_ok else "failed",
            "messages": integrity_messages,
        },
    }


def check_migration_ledger_integrity(db_path: str) -> dict[str, Any]:
    ledger = get_schema_migration_status(db_path)
    return {
        "status": "ok" if ledger["status"] == "ok" else "failed",
        "ledger_status": ledger["status"],
        "current_schema_version": ledger["current_schema_version"],
        "expected_migrations": ledger["expected_migrations"],
        "applied_count": ledger["applied_count"],
        "pending_migrations": ledger["pending_migrations"],
        "unknown_migrations": ledger["unknown_migrations"],
    }


def check_database_integrity(db_path: str) -> dict[str, Any]:
    replay = check_replay_consistency(db_path)
    event_chain = check_event_chain_consistency(db_path)
    sqlite = check_sqlite_integrity(db_path)
    migrations = check_migration_ledger_integrity(db_path)
    checks = {
        "replay": replay,
        "event_chain": event_chain,
        "sqlite": sqlite,
        "migrations": migrations,
    }
    return {
        "status": "ok" if all(check["status"] == "ok" for check in checks.values()) else "failed",
        "checks": checks,
    }


def check_project_replay_integrity(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    include_deleted: bool = True,
) -> dict[str, Any]:
    where = ["project_id = ?"]
    if not include_deleted:
        where.append("deleted_at IS NULL")
    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.INTEGRITY_READ,
        )
        documents = conn.execute(
            f"""
            SELECT *
            FROM json_documents
            WHERE {" AND ".join(where)}
            ORDER BY full_path ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        reports = []
        for document in documents:
            event_rows = conn.execute(
                """
                SELECT *
                FROM document_events
                WHERE document_id = ?
                ORDER BY result_version ASC, id ASC
                """,
                (document["id"],),
            ).fetchall()
            reports.append(_replay_report_from_rows(document, event_rows))
        failures = [report for report in reports if report["status"] != "ok"]
        return {
            "project_id": project_id,
            "status": "ok" if not failures else "failed",
            "include_deleted": include_deleted,
            "checked_documents": len(reports),
            "failure_count": len(failures),
            "documents": reports,
            "failures": failures,
        }


def check_project_event_chain_integrity(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    include_deleted: bool = True,
) -> dict[str, Any]:
    where = ["project_id = ?"]
    if not include_deleted:
        where.append("deleted_at IS NULL")
    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.INTEGRITY_READ,
        )
        documents = conn.execute(
            f"""
            SELECT *
            FROM json_documents
            WHERE {" AND ".join(where)}
            ORDER BY full_path ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        reports = []
        for document in documents:
            event_rows = conn.execute(
                """
                SELECT *
                FROM document_events
                WHERE document_id = ?
                ORDER BY result_version ASC, id ASC
                """,
                (document["id"],),
            ).fetchall()
            reports.append(_event_chain_report_from_rows(document, event_rows))
        failures = [report for report in reports if report["status"] != "ok"]
        return {
            "project_id": project_id,
            "status": "ok" if not failures else "failed",
            "include_deleted": include_deleted,
            "checked_documents": len(reports),
            "failure_count": len(failures),
            "documents": reports,
            "failures": failures,
        }


def check_document_replay_integrity(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_actor(conn, actor_id)
        document = conn.execute(
            """
            SELECT *
            FROM json_documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
        if document is None:
            raise AppError(
                ErrorCode.DOCUMENT_NOT_FOUND,
                "Document not found.",
                {"document_id": document_id},
            )
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=document["project_id"],
            permission=ProjectPermission.INTEGRITY_READ,
        )
        event_rows = conn.execute(
            """
            SELECT *
            FROM document_events
            WHERE document_id = ?
            ORDER BY result_version ASC, id ASC
            """,
            (document_id,),
        ).fetchall()
        report = _replay_report_from_rows(document, event_rows)
        failures = [] if report["status"] == "ok" else [report]
        return {
            "document_id": document_id,
            "project_id": document["project_id"],
            "status": report["status"],
            "failure_count": len(failures),
            "document": report,
            "failures": failures,
        }


def check_document_event_chain_integrity(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_actor(conn, actor_id)
        document = conn.execute(
            """
            SELECT *
            FROM json_documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
        if document is None:
            raise AppError(
                ErrorCode.DOCUMENT_NOT_FOUND,
                "Document not found.",
                {"document_id": document_id},
            )
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=document["project_id"],
            permission=ProjectPermission.INTEGRITY_READ,
        )
        event_rows = conn.execute(
            """
            SELECT *
            FROM document_events
            WHERE document_id = ?
            ORDER BY result_version ASC, id ASC
            """,
            (document_id,),
        ).fetchall()
        return _event_chain_report_from_rows(document, event_rows)
