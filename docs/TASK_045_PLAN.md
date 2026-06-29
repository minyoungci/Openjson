# TASK_045 Plan - Malformed Schema JSON Diagnostics

## Goal

Make malformed persisted `schemas.schema_json` diagnosable and safe.

Schema documents are validated on normal creation, but a local SQLite database
can still be corrupted manually or by a failed external migration. Core
document mutations must not partially write when a bound schema row is
malformed, and schema read/report/export surfaces should not expose raw decoder
exceptions.

## Non-Goals

- No schema repair, schema rewrite, schema update API, or schema deactivation
  API.
- No DB schema change.
- No change to JSON Schema Draft 2020-12 validation policy.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Surfaces

- `GET /schemas/{schema_id}`
- `GET /projects/{project_id}/schemas`
- `GET /schemas/{schema_id}/usage`
- `GET /projects/{project_id}/validation-report`
- `GET /projects/{project_id}/export`
- schema-bound document create, patch, rollback, and validate paths

## Behavior

For metadata/report/export reads:

- schema metadata remains readable
- malformed `schema_json` is represented as `schema: null`
- response includes `schema_json_error`
- schema usage and validation report mark affected validations invalid with
  `validator: "schema_json_syntax"`

For schema-bound document mutations or validation calls:

- request returns the standard error envelope
- error code is `INTERNAL_ERROR`
- `details.diagnostic_code` is `SCHEMA_JSON_DECODE_FAILED`
- details include schema id, project id, schema name/version, field, and JSON
  decoder details
- mutation endpoints do not create documents, insert events, or update
  snapshots

## Data Model

No schema change.

The schema row remains immutable. This task only changes how malformed
persisted schema JSON is loaded and reported.

## Tests

- Schema get/list reports malformed `schema_json` without throwing.
- Schema-bound create rejects malformed schema JSON without creating a document
  or event.
- Schema-bound patch/rollback reject malformed schema JSON without partial
  mutation.
- Schema usage and validation report expose `schema_json_syntax` validation
  failures.
- Project export includes schema metadata and `schema_json_error`.
