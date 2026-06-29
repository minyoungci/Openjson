# TASK_056 Plan - API Token Restore and Rollback Actor Tests

## Goal

Pin down project API token behavior on restore and rollback document mutation
endpoints.

Restore and rollback are trust-critical foundation operations. When a bearer
token restores a soft-deleted document or rolls a document back to an earlier
version, the normal document event pipeline must be used and
`document_events.actor_id` must be the token owner's user id. Replay must still
reconstruct the latest snapshot after these token-authenticated mutations.

## Non-Goals

- No new API token endpoint.
- No token expiry, rotation, rate limiting, or admin-wide token management.
- No DB schema change.
- No alternate token-specific document event type.
- No change to rollback semantics.
- No document/event/snapshot mutation outside the existing document pipeline.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Endpoints

- `POST /documents/{document_id}/restore`
- `POST /documents/{document_id}/rollback`
- `GET /documents/{document_id}/history`

## Behavior

For a valid bearer token scoped to a project:

- restoring a soft-deleted document creates a normal `restore` event
- rollback creates a new `rollback` event rather than deleting old events
- restore and rollback events record `actor_id` as the token owner
- replay still reconstructs the latest snapshot after token-authenticated
  restore and rollback

## Data Model

No schema change.

This task only adds regression coverage around the existing `api_tokens`,
`json_documents`, and append-only `document_events` boundary.

## Tests

- Bearer-token restore records the token owner as event actor and preserves
  replay consistency.
- Bearer-token rollback records the token owner as event actor, appends a new
  rollback event, and preserves replay consistency.
