# TASK_055 Plan - API Token Document Mutation Actor Tests

## Goal

Pin down project API token behavior on canonical document mutation endpoints.

Project API tokens act as their owning user. When a bearer token creates,
patches, or deletes a JSON document, the normal document event pipeline must be
used and `document_events.actor_id` must be the token owner's user id. Replay
must still reconstruct the latest snapshot after token-authenticated mutations.

## Non-Goals

- No new API token endpoint.
- No token expiry, rotation, rate limiting, or admin-wide token management.
- No DB schema change.
- No alternate token-specific document event type.
- No document/event/snapshot mutation outside the existing document pipeline.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Endpoints

- `POST /projects/{project_id}/documents`
- `PATCH /documents/{document_id}`
- `DELETE /documents/{document_id}`
- `GET /documents/{document_id}/history`

## Behavior

For a valid bearer token scoped to a project:

- document creation succeeds when the token owner has document write access
- document patch succeeds when `base_version` matches
- document delete creates the normal soft-delete event
- every created document event records `actor_id` as the token owner
- replay still reconstructs the latest snapshot after token-authenticated
  create, patch, and delete

## Data Model

No schema change.

This task only adds regression coverage around the existing `api_tokens`,
`json_documents`, and append-only `document_events` boundary.

## Tests

- Bearer-token document create/patch/delete records the token owner as event
  actor.
- Bearer-token document history returns the expected create/update/delete
  event sequence.
- Replay consistency holds after token-authenticated document mutations.
