# TASK_041 Plan - Document Event Detail Malformed JSON Diagnostics

## Goal

Extend malformed persisted JSON diagnostics to the document event detail API.

The event detail API opens a single append-only `document_events` row. Because
the event log is the audit source of truth, callers should still be able to
inspect event metadata when one of the event JSON fields is malformed because
of database corruption or manual tampering.

## Non-Goals

- No event mutation, event rewriting, repair, or compaction.
- No document mutation, audit mutation, schema mutation, or snapshot write.
- No new persisted event detail table or cache.
- No UI diff view.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No complex path-level permission model.

## Behavior

For malformed `document_events` JSON fields on the requested event:

- endpoint still returns the event detail payload for authorized reads
- malformed parsed field is returned as `null`
- event includes `json_errors` with field and decoder details
- `include_snapshots=false` keeps the existing snapshots shape
- `include_snapshots=true` returns `snapshots.error` instead of raising a
  server error when reconstruction cannot safely proceed

Covered fields:

- `patch`
- `inverse_patch`
- `changed_paths`
- `before_values`
- `after_values`

## Data Model

No schema change.

The endpoint remains read-only. It reports malformed event JSON but does not
repair the event log or latest snapshot.

## Tests

- Service-level event detail reports malformed event JSON without snapshots.
- HTTP event detail with `include_snapshots=true` reports snapshot
  reconstruction failure without returning a server error.
