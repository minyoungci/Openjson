# TASK_039 Plan - Project Export Malformed JSON Diagnostics

## Goal

Extend malformed persisted JSON diagnostics to the project export archive API.

The project export archive is read-only but still walks latest document
snapshots and append-only document events. If a database is corrupted or
manually tampered with, export should return an archive payload with failed
integrity diagnostics instead of raising a JSON decoder server error.

## Non-Goals

- No document mutation, event mutation, snapshot repair, or event compaction.
- No migration repair, migration deletion, or schema rewrite.
- No persisted export table, background export job, or export cache.
- No Git import/export integration.
- No UI work.
- No branch, pull request, realtime collaboration, WebSocket, offline sync,
  merge automation, or AI features.
- No complex path-level permission model.

## Behavior

For malformed `json_documents.current_snapshot_json`:

- export still returns the project archive payload
- affected document has `content: null`
- affected document includes `content_error`
- `integrity.status` is `failed`
- replay and event-chain checks expose `SNAPSHOT_JSON_DECODE_FAILED`

For malformed document event JSON fields:

- export still returns the project archive payload
- affected event has the malformed parsed field set to `null`
- affected event includes `json_errors`
- `integrity.status` is `failed`
- replay and event-chain checks expose `EVENT_JSON_DECODE_FAILED`

## Data Model

No schema change.

The export archive now uses the integrity service row-based report builders for
document replay and event-chain diagnostics. The checker remains read-only and
does not repair malformed persisted JSON.

## Tests

- Service-level export reports malformed latest snapshot JSON without crashing.
- HTTP export reports malformed document event JSON without returning a server
  error.
- Normal export shape remains unchanged for healthy persisted JSON.
