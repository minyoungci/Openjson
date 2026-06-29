# TASK_053 Plan - API Token Audit Atomicity Tests

## Goal

Prove that accepted project API token management operations and their success
audit rows are atomic.

TASK_012 requires token creation and revocation to write `audit_log` rows while
keeping token secrets out of persistent storage. If the success audit write
fails, the token mutation must roll back and only the rejected attempt should be
recorded as a failure audit row.

## Non-Goals

- No new API token endpoint.
- No token expiry, rotation, rate limiting, or admin-wide token management.
- No DB schema change.
- No document/event/snapshot mutation.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Operations

- `create_project_api_token`
- `revoke_project_api_token`

## Behavior

When the success audit write fails:

- the token mutation is rolled back
- a failure audit row is recorded for the rejected attempt
- no success audit row is committed for the failed operation
- no document event is created
- raw token secrets are not persisted

## Data Model

No schema change.

This task only adds a regression boundary around the existing `api_tokens` and
append-only `audit_log` tables.

## Tests

- Forced success audit failure during API token creation does not insert the
  token.
- Forced success audit failure during API token revocation preserves
  `revoked_at = NULL`.
- Each forced failure records a failure audit row and no success audit row for
  the failed operation.
- API token audit failures do not create `document_events`.
