from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.database import connect, utc_now
from app.document_service import (
    _document_row_including_deleted,
    _dump_field,
    _events_for_replay,
    _load_document_snapshot,
)
from app.errors import AppError, ErrorCode
from app.json_patch import PatchApplyError, apply_patch
from app.replay import replay_events


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _row_to_snapshot(row: sqlite3.Row, *, created: bool | None = None) -> dict[str, Any]:
    result = {
        "id": row["id"],
        "document_id": row["document_id"],
        "version": row["version"],
        "source_event_id": row["source_event_id"],
        "created_at": row["created_at"],
        "snapshot_json_bytes": len(row["snapshot_json"].encode("utf-8")),
    }
    if created is not None:
        result["created"] = created
    return result


def _load_compacted_snapshot(row: sqlite3.Row) -> Any:
    try:
        return json.loads(row["snapshot_json"])
    except json.JSONDecodeError as exc:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Compacted document snapshot JSON is malformed.",
            {
                "diagnostic_code": "DOCUMENT_SNAPSHOT_JSON_DECODE_FAILED",
                "snapshot_id": row["id"],
                "document_id": row["document_id"],
                "version": row["version"],
                "message": exc.msg,
                "line": exc.lineno,
                "column": exc.colno,
                "position": exc.pos,
            },
        ) from exc


def _source_event_for_version(events: list[dict[str, Any]], version: int) -> dict[str, Any]:
    for event in events:
        if event["result_version"] == version:
            return event
    raise AppError(
        ErrorCode.DOCUMENT_VERSION_NOT_FOUND,
        "Document version not found.",
        {"target_version": version},
    )


def _ensure_replay_matches_latest(row: sqlite3.Row, events: list[dict[str, Any]]) -> Any:
    expected_latest = _load_document_snapshot(row)
    replayed_latest = replay_events(events, target_version=row["current_version"])
    if replayed_latest != expected_latest:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Event replay does not match latest snapshot; compacted snapshot was not written.",
            {"document_id": row["id"], "current_version": row["current_version"]},
        )
    return replayed_latest


def compact_document_snapshot(
    db_path: str,
    *,
    document_id: str,
    version: int | None = None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        document = _document_row_including_deleted(conn, document_id)
        target_version = document["current_version"] if version is None else version
        if target_version <= 0:
            raise AppError(
                ErrorCode.INVALID_VERSION_RANGE,
                "Compacted snapshot version must be a positive document version.",
                {"version": target_version},
            )

        events = _events_for_replay(conn, document_id)
        source_event = _source_event_for_version(events, target_version)
        latest_snapshot = _ensure_replay_matches_latest(document, events)
        target_snapshot = (
            latest_snapshot
            if target_version == document["current_version"]
            else replay_events(events, target_version=target_version)
        )
        target_snapshot_json = _dump_field(target_snapshot)

        existing = conn.execute(
            """
            SELECT *
            FROM document_snapshots
            WHERE document_id = ? AND version = ?
            """,
            (document_id, target_version),
        ).fetchone()
        if existing is not None:
            if _load_compacted_snapshot(existing) != target_snapshot or existing["source_event_id"] != source_event["id"]:
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    "Stored compacted snapshot does not match replayed event log.",
                    {
                        "snapshot_id": existing["id"],
                        "document_id": document_id,
                        "version": target_version,
                    },
                )
            return _row_to_snapshot(existing, created=False)

        snapshot_id = _new_id("snap")
        conn.execute(
            """
            INSERT INTO document_snapshots (
                id,
                document_id,
                version,
                snapshot_json,
                source_event_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                document_id,
                target_version,
                target_snapshot_json,
                source_event["id"],
                utc_now(),
            ),
        )
        inserted = conn.execute(
            """
            SELECT *
            FROM document_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        return _row_to_snapshot(inserted, created=True)


def list_document_snapshots(db_path: str, *, document_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        _document_row_including_deleted(conn, document_id)
        rows = conn.execute(
            """
            SELECT *
            FROM document_snapshots
            WHERE document_id = ?
            ORDER BY version ASC
            """,
            (document_id,),
        ).fetchall()
        return {
            "document_id": document_id,
            "snapshots": [_row_to_snapshot(row) for row in rows],
        }


def reconstruct_document_at_version_with_compaction(
    db_path: str,
    *,
    document_id: str,
    version: int,
) -> dict[str, Any]:
    if version <= 0:
        raise AppError(
            ErrorCode.INVALID_VERSION_RANGE,
            "Document version must be positive.",
            {"version": version},
        )
    with connect(db_path) as conn:
        document = _document_row_including_deleted(conn, document_id)
        events = _events_for_replay(conn, document_id)
        _source_event_for_version(events, version)
        _ensure_replay_matches_latest(document, events)

        compacted = conn.execute(
            """
            SELECT *
            FROM document_snapshots
            WHERE document_id = ? AND version <= ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (document_id, version),
        ).fetchone()
        if compacted is None:
            return {
                "document_id": document_id,
                "version": version,
                "content": replay_events(events, target_version=version),
                "used_compacted_snapshot": False,
                "compacted_snapshot": None,
                "replayed_event_count": sum(1 for event in events if event["result_version"] <= version),
            }

        state = _load_compacted_snapshot(compacted)
        replayed_event_count = 0
        for event in events:
            if event["result_version"] <= compacted["version"]:
                continue
            if event["result_version"] > version:
                break
            if not event["patch"]:
                continue
            try:
                state = apply_patch(state, event["patch"]).document
            except PatchApplyError as exc:
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    "Stored document event replay failed.",
                    {"event_id": event["id"], "message": str(exc)},
                ) from exc
            replayed_event_count += 1

        return {
            "document_id": document_id,
            "version": version,
            "content": state,
            "used_compacted_snapshot": True,
            "compacted_snapshot": _row_to_snapshot(compacted),
            "replayed_event_count": replayed_event_count,
        }


def compact_due_document_snapshots(
    db_path: str,
    *,
    document_id: str | None = None,
    every_versions: int = 100,
    include_latest: bool = True,
) -> dict[str, Any]:
    if every_versions <= 0:
        raise AppError(
            ErrorCode.INVALID_VERSION_RANGE,
            "Snapshot compaction interval must be positive.",
            {"every_versions": every_versions},
        )

    with connect(db_path) as conn:
        if document_id:
            documents = [_document_row_including_deleted(conn, document_id)]
        else:
            documents = list(
                conn.execute(
                    """
                    SELECT *
                    FROM json_documents
                    ORDER BY created_at ASC, id ASC
                    """
                ).fetchall()
            )
        due_versions_by_document: dict[str, list[int]] = {}
        for document in documents:
            rows = conn.execute(
                """
                SELECT result_version
                FROM document_events
                WHERE document_id = ? AND result_version % ? = 0
                ORDER BY result_version ASC
                """,
                (document["id"], every_versions),
            ).fetchall()
            versions = [row["result_version"] for row in rows]
            if include_latest and document["current_version"] not in versions:
                versions.append(document["current_version"])
            due_versions_by_document[document["id"]] = sorted(versions)

    snapshots = []
    created_count = 0
    existing_count = 0
    for due_document_id, versions in due_versions_by_document.items():
        for due_version in versions:
            snapshot = compact_document_snapshot(db_path, document_id=due_document_id, version=due_version)
            snapshots.append(snapshot)
            if snapshot["created"]:
                created_count += 1
            else:
                existing_count += 1

    return {
        "status": "ok",
        "documents_checked": len(due_versions_by_document),
        "snapshots_created": created_count,
        "snapshots_existing": existing_count,
        "snapshots": snapshots,
    }
