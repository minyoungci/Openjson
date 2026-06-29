# TASK_061 Plan - API Token Document Validate Read Surface

## Goal

Pin down project API token behavior on the document validation endpoint.

`POST /documents/{document_id}/validate` is a read-only trust surface over the
latest canonical snapshot and optional schema binding. Bearer-token requests
must preserve project scope, RBAC, and read-only behavior while returning the
same schema validation result shape used by actor-header requests.

## Non-Goals

- No new API token endpoint.
- No token expiry, rotation, rate limiting, or admin-wide token management.
- No DB schema change.
- No new schema selection or validation algorithm.
- No document/event/snapshot mutation.
- No document editor UI.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Covered Endpoint

- `POST /documents/{document_id}/validate`

## Behavior

For a valid bearer token scoped to a project:

- schema-bound valid documents return `valid=true`
- schema-bound invalid documents return `valid=false` and JSON Pointer error
  paths
- unbound documents return `valid=true` with the existing no-schema warning
- validate requests do not create `document_events`, update snapshots, or
  change versions
- tokens scoped to another project return `PERMISSION_DENIED`
- token owners without `document:validate` permission return
  `PERMISSION_DENIED`

## Data Model

No schema change.

This task only adds regression coverage around the existing `api_tokens`,
`schemas`, `json_documents`, and read-only document validation boundary.

## Tests

- Bearer-token validate returns valid, invalid, and unbound validation payloads
  without mutating event counts, snapshots, or versions.
- Bearer-token validate enforces project scope and project-role validate
  permission.
