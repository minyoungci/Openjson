# TASK_067 Plan - HTTP JSON Pointer Read Filter Errors

## Goal

Lock the HTTP error contract for malformed JSON Pointer read filters.

TASK_066 covers the service-layer behavior for read-only filters. This task
adds API-level regression coverage so FastAPI routes expose the same
`INVALID_REQUEST` error format for malformed escaped JSON Pointer filters.

## Non-Goals

- No new read filter semantics.
- No query language or search index.
- No DB schema change.
- No document/event/snapshot mutation.
- No document editor UI.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Covered Surfaces

- `GET /projects/{project_id}/document-search?path=...`
- `GET /projects/{project_id}/document-events?changed_path=...`

## Behavior

- malformed escaped read filters return HTTP 400
- error body uses the standard `{ "error": { ... } }` envelope
- error code is `INVALID_REQUEST`
- rejected HTTP read filters create no document events
- rejected HTTP read filters do not mutate latest snapshots

## Data Model

No schema change.

## Tests

- Document search HTTP route rejects malformed escaped `path`.
- Project document event feed HTTP route rejects malformed escaped
  `changed_path`.
- Rejected HTTP read filters do not change document event counts or snapshots.
