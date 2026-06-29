# TASK_054 Plan - API Token Schema Scope Tests

## Goal

Pin down the project-scoped API token boundary for schema resources.

Schema registry endpoints are part of the JSON validation foundation. A
project-scoped token must be able to read schemas in its own project, must not
read schemas from another project, and must return the endpoint's normal
not-found error for missing schema ids instead of exposing another project.

## Non-Goals

- No new API token endpoint.
- No token expiry, rotation, rate limiting, or admin-wide token management.
- No schema update or deactivate endpoint.
- No DB schema change.
- No document/event/snapshot mutation.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Endpoints

- `GET /schemas/{schema_id}`
- `GET /schemas/{schema_id}/usage`

## Behavior

For a valid bearer token scoped to project A:

- reading a schema in project A succeeds
- reading schema usage for a schema in project A succeeds
- reading a schema in project B returns `PERMISSION_DENIED`
- reading schema usage for a schema in project B returns `PERMISSION_DENIED`
- reading a missing schema id returns `SCHEMA_NOT_FOUND`

## Data Model

No schema change.

This task only adds regression coverage for the existing `schemas` and
`api_tokens` boundary.

## Tests

- Same-project schema read and usage work with a bearer token.
- Cross-project schema read and usage are denied with the standard error
  envelope.
- Missing schema read and usage return the standard schema not-found envelope.
