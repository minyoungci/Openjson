# TASK_062 Plan - Empty Update Patch Rejection

## Goal

Reject empty user-submitted document update patches.

An accepted `PATCH /documents/{document_id}` request creates an append-only
`document_events` row and increments the document version. Empty update patches
would create a new version without any changed path, before value, or after
value, which weakens the event log as an auditable change history.

## Non-Goals

- No new patch operation support.
- No JSON Patch move, copy, or test support.
- No semantic no-op detection for equal before/after values.
- No DB schema change.
- No change to delete, restore, or rollback event formats.
- No document editor UI.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Covered Endpoint

- `PATCH /documents/{document_id}`

## Behavior

For user-submitted document update patches:

- `patch` must be a list
- `patch` must contain at least one operation
- empty patches return `PATCH_APPLY_FAILED`
- empty patches create no `document_events` row
- empty patches do not update `current_snapshot_json`
- empty patches do not increment `current_version`

Delete and restore events still store empty `patch` and `inverse_patch` arrays
because they are distinct mutation APIs with explicit event types.

## Data Model

No schema change.

This task only strengthens validation before the existing document update
transaction writes an event and latest snapshot.

## Tests

- Service-level empty patch rejection preserves event count, snapshot, and
  version.
- HTTP empty patch rejection returns the standard error envelope and preserves
  event count, snapshot, and version.
