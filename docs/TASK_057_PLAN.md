# TASK_057 Plan - API Token Replay Read Surface Tests

## Goal

Pin down project API token behavior on replay-dependent document read surfaces.

Version snapshots, diffs, and event details with reconstructed snapshots must
derive from the append-only `document_events` log. When a bearer token reads
these surfaces, project scope must still be enforced and the response must
reflect the same event-log reconstruction used by actor-header requests.

## Non-Goals

- No new API token endpoint.
- No token expiry, rotation, rate limiting, or admin-wide token management.
- No DB schema change.
- No new replay algorithm.
- No document/event/snapshot mutation.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Endpoints

- `GET /documents/{document_id}/history/{version}`
- `GET /documents/{document_id}/diff`
- `GET /documents/{document_id}/events/{event_id}?include_snapshots=true`

## Behavior

For a valid bearer token scoped to a project:

- version snapshot reads reconstruct the requested version from
  `document_events`
- diff reads compare reconstructed snapshots for the requested versions
- event detail snapshot reads reconstruct before/after snapshots from
  `document_events`
- cross-project document replay read surfaces return `PERMISSION_DENIED`

## Data Model

No schema change.

This task only adds regression coverage around the existing `api_tokens`,
`json_documents`, and append-only `document_events` read boundary.

## Tests

- Bearer-token version snapshot, diff, and event detail snapshot reads return
  event-log-derived values.
- Bearer-token replay read surfaces preserve project scope for other-project
  documents.
