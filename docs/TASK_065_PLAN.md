# TASK_065 Plan - Strict JSON Pointer Escaping

## Goal

Reject malformed JSON Pointer escape sequences.

JSON path-level auditability depends on paths being unambiguous. JSON Pointer
only allows `~0` for `~` and `~1` for `/`. Paths containing sequences such as
`~2` or a trailing `~` must not be accepted into document events or read-surface
filters.

## Non-Goals

- No new patch operation support.
- No schema validation behavior change.
- No migration or rewrite of existing stored events.
- No DB schema change.
- No document editor UI.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Covered Surfaces

- `PATCH /documents/{document_id}`
- `GET /documents/{document_id}/path-history`
- `GET /documents/{document_id}/blame`
- other existing callers of shared JSON Pointer parsing

## Behavior

- valid escapes such as `/a~1b` and `/c~0d` continue to work
- invalid escapes such as `/a~2b` are rejected
- trailing `~` is rejected
- failed patch requests create no `document_events` row
- failed patch requests do not update `current_snapshot_json`
- failed patch requests do not increment `current_version`
- read-surface invalid paths return `INVALID_REQUEST`

## Data Model

No schema change.

This task only strengthens shared JSON Pointer parsing before event metadata or
read filters use a path.

## Tests

- Service-level invalid JSON Pointer escape in update patch is rejected without
  event, snapshot, or version mutation.
- Path-history and blame invalid JSON Pointer escapes return
  `INVALID_REQUEST` without mutation.
