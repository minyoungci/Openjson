# TASK_044 Plan - Core Document Snapshot Malformed JSON Diagnostics

## Goal

Make core document-service paths return structured diagnostics when
`json_documents.current_snapshot_json` is malformed.

Integrity, export, validation report, and schema usage surfaces already report
malformed latest snapshots. This task applies the same reliability principle to
core document read and mutation paths so a corrupted latest snapshot does not
surface as a raw decoder exception or allow partial writes.

## Non-Goals

- No document repair, snapshot rewrite, event replay repair, or compaction.
- No DB schema change.
- No change to valid document mutation semantics.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Surfaces

- `GET /documents/{document_id}`
- `PATCH /documents/{document_id}`
- `DELETE /documents/{document_id}`
- `POST /documents/{document_id}/restore`
- `POST /documents/{document_id}/rollback`
- `POST /documents/{document_id}/validate`
- internal replay assertion helper latest-snapshot comparison

`GET /projects/{project_id}/document-search` originally shared this policy,
but TASK_049 reclassified it as a read-only partial-diagnostic surface.

## Behavior

When `current_snapshot_json` is malformed:

- the request returns the standard error envelope
- error code is `INTERNAL_ERROR`
- `details.diagnostic_code` is `SNAPSHOT_JSON_DECODE_FAILED`
- details include document id, project id, full path, current version, field,
  and JSON decoder details
- mutation endpoints do not insert events, update snapshots, or change soft
  delete state

## Data Model

No schema change.

This is a diagnostic and transaction-safety hardening layer only.

## Tests

- Document get returns structured malformed snapshot error.
- Canonical document read returns structured malformed snapshot error.
- Patch rejects malformed latest snapshot without inserting an event.
- Delete rejects malformed latest snapshot without inserting an event or
  setting `deleted_at`.
- Rollback rejects malformed latest snapshot without inserting an event or
  changing the stored malformed snapshot.
