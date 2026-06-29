# TASK_058 Plan - API Token Path History and Blame Tests

## Goal

Pin down project API token behavior on path-level history and blame read
surfaces.

Path history and blame are core trust surfaces for a JSON-native collaborative
workspace. When a bearer token reads these surfaces, the response must be
derived from append-only `document_events`, preserve path-level before/after
tracking, and enforce project scope.

## Non-Goals

- No new API token endpoint.
- No token expiry, rotation, rate limiting, or admin-wide token management.
- No DB schema change.
- No new path history or blame algorithm.
- No document/event/snapshot mutation.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Endpoints

- `GET /documents/{document_id}/path-history`
- `GET /documents/{document_id}/blame`

## Behavior

For a valid bearer token scoped to a project:

- path history reads return event-log-derived path changes
- blame reads return the latest path-changing event
- path-level actor attribution is the token owner's user id for
  token-authenticated mutations
- cross-project path history and blame reads return `PERMISSION_DENIED`

## Data Model

No schema change.

This task only adds regression coverage around the existing `api_tokens`,
`json_documents`, and append-only `document_events` read boundary.

## Tests

- Bearer-token path history and blame reads return event-log-derived
  before/after values and token-owner attribution.
- Bearer-token path history and blame preserve project scope for other-project
  documents.
