# TASK_059 Plan - API Token Schema Validation Mutation Atomicity

## Goal

Pin down schema-bound document mutation behavior when requests authenticate
with project API tokens.

Bearer-token document mutations must use the same JSON Schema validation
boundary as actor-header mutations: validation happens before document/event
writes, and failed validation leaves no partial document, event, snapshot, or
version change.

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

- `POST /projects/{project_id}/documents`
- `PATCH /documents/{document_id}`

## Behavior

For a valid bearer token scoped to a project:

- schema file-pattern auto-binding applies on document create
- schema validation failures return `SCHEMA_VALIDATION_FAILED`
- invalid schema-bound creates insert no `json_documents` row and no
  `document_events` row
- invalid schema-bound patches create no new `document_events` row, do not
  change `json_documents.current_snapshot_json`, and do not increment
  `json_documents.current_version`
- accepted mutations still satisfy the replay invariant

## Data Model

No schema change.

This task only adds regression coverage around the existing `api_tokens`,
`schemas`, `json_documents`, and append-only `document_events` boundary.

## Tests

- Bearer-token schema-invalid create through file-pattern auto-binding returns
  `SCHEMA_VALIDATION_FAILED` without inserting document or event rows.
- Bearer-token schema-invalid patch against a schema-bound document returns
  `SCHEMA_VALIDATION_FAILED` without adding an event, changing the snapshot, or
  incrementing the version.
