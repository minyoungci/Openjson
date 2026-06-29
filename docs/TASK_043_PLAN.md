# TASK_043 Plan - Replay-Dependent Malformed Event JSON Errors

## Goal

Make replay-dependent document APIs fail with a structured error when persisted
`document_events` JSON fields are malformed.

TASK_042 keeps metadata-oriented read surfaces inspectable. This task covers
surfaces that must reconstruct a trustworthy JSON snapshot from the append-only
event log. If event replay cannot safely load the event chain, the request must
not continue with a partial or guessed snapshot.

## Non-Goals

- No event mutation, event rewriting, repair, compaction, or deletion.
- No document mutation when replay input is malformed.
- No DB schema change.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Surfaces

The shared replay loader is used by:

- `GET /documents/{document_id}/history/{version}`
- `GET /documents/{document_id}/diff`
- `POST /documents/{document_id}/rollback`
- internal replay helpers such as `reconstruct_document_at_version`,
  `replay_latest_snapshot`, and `assert_replay_matches_latest`

## Behavior

When a stored event JSON field is malformed:

- replay loading stops before reconstruction
- the API returns the standard error envelope
- error code is `INTERNAL_ERROR`
- `details.diagnostic_code` is `EVENT_JSON_DECODE_FAILED`
- details include document id, event id, version metadata, and JSON decoder
  failure details
- mutation endpoints such as rollback leave the document snapshot and event log
  unchanged

## Data Model

No schema change.

This task only changes how malformed persisted event JSON is surfaced to
callers. It does not repair data and does not weaken append-only event
semantics.

## Tests

- Version snapshot reconstruction raises structured `INTERNAL_ERROR`.
- Diff raises structured `INTERNAL_ERROR`.
- Rollback rejects malformed replay input without inserting an event or
  changing the snapshot.
- HTTP version/diff responses use the standard error envelope.
