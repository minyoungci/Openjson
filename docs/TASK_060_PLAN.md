# TASK_060 Plan - API Token Schema Validation Restore and Rollback Atomicity

## Goal

Pin down schema validation atomicity for bearer-token restore and rollback
document mutations.

Restore and rollback are trust-critical mutation paths because they create new
append-only document events while reusing existing snapshots reconstructed from
storage. When a project API token triggers these mutations, schema validation
must happen before any restore or rollback event is inserted and before
`json_documents` metadata changes.

## Non-Goals

- No new API token endpoint.
- No token expiry, rotation, rate limiting, or admin-wide token management.
- No DB schema change.
- No new schema selection or validation algorithm.
- No document editor UI.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Covered Endpoints

- `POST /documents/{document_id}/restore`
- `POST /documents/{document_id}/rollback`

## Behavior

For a valid bearer token scoped to a project:

- schema validation failures during restore return `SCHEMA_VALIDATION_FAILED`
- invalid restore attempts create no restore event, do not clear `deleted_at`,
  and do not increment `current_version`
- schema validation failures during rollback return `SCHEMA_VALIDATION_FAILED`
- invalid rollback attempts create no rollback event, do not update
  `current_snapshot_json`, and do not increment `current_version`
- accepted prior document events remain replay-consistent with the latest
  snapshot

## Data Model

No schema change.

This task only adds regression coverage around the existing `api_tokens`,
`schemas`, `json_documents`, and append-only `document_events` boundary.

## Tests

- Bearer-token schema-invalid restore preserves event count, `deleted_at`, and
  version.
- Bearer-token schema-invalid rollback preserves event count, latest snapshot,
  and version.
