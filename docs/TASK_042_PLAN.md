# TASK_042 Plan - Document Event Read Surface Malformed JSON Diagnostics

## Goal

Extend malformed persisted event JSON diagnostics beyond the single event
detail endpoint to the other read-only event surfaces.

The append-only event log is the audit source of truth. If a stored event JSON
field is malformed because of database corruption or manual tampering, callers
should still be able to inspect event metadata where possible, and replay-based
read surfaces should return an explicit diagnostic instead of an unhandled
server error.

## Non-Goals

- No event mutation, event rewriting, repair, compaction, or deletion.
- No document mutation, audit mutation, schema mutation, or snapshot write.
- No DB schema change.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered APIs

- `GET /documents/{document_id}/history`
- `GET /projects/{project_id}/document-events`
- `GET /documents/{document_id}/path-history`
- `GET /documents/{document_id}/blame`

## Behavior

For malformed event JSON fields in history and project event feed responses:

- endpoint still returns authorized event metadata
- malformed parsed field is returned as `null`
- event includes `json_errors` with field and decoder details

For path-history and blame responses:

- reconstruction stops when a malformed event is encountered
- endpoint returns a read-only `replay_error`
- `latest` and `blame` are `null` because current path state cannot be trusted
- already reconstructed earlier changes may still be returned for inspection

Covered event JSON fields:

- `patch`
- `inverse_patch`
- `changed_paths`
- `before_values`
- `after_values`

## Data Model

No schema change.

The change is a read-only diagnostic layer over existing `document_events`
rows. It does not repair malformed rows and does not change append-only event
semantics.

## Tests

- Document history returns malformed event metadata with `json_errors`.
- Project event feed returns malformed event metadata with `json_errors`.
- Project event feed `changed_path` filtering does not fail on malformed
  `changed_paths`.
- Path history returns `replay_error` instead of raising on malformed event
  JSON.
- Blame returns the same `replay_error` when path reconstruction cannot be
  trusted.
