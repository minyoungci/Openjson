# TASK_099_PLAN.md

## Objective

Improve the local non-realtime editor shell so schema validation failures are
displayed as actionable JSON Pointer-level diagnostics.

This task makes failed create, preview, and save attempts easier to understand
without changing the backend mutation model.

## Explicit Non-Scope

This task does not implement realtime collaboration, WebSocket, presence,
offline sync, merge/conflict auto-resolution, Git integration, branching, pull
requests, AI features, full authentication, invitation flow, schema update or
deactivation APIs, draft persistence, or complex path-level permissions.

## UI Behavior

When an API response returns `SCHEMA_VALIDATION_FAILED`, the editor renders the
validation details in the Validation inspector instead of only showing a generic
request error.

Rendered validation diagnostics include, when present:

- JSON Pointer path,
- validator keyword,
- expected value,
- actual value,
- message.

The same routing applies to:

- document creation,
- content preview,
- content save.

Syntax errors still remain local/editor parsing errors or
`INVALID_JSON_SYNTAX` diagnostics. Version conflicts still use the existing
conflict preview and recovery controls.

## Persistence Boundary

No database schema changes and no backend mutation endpoints are introduced.

Failed schema validation must remain non-mutating:

- no `json_documents` row for failed creates,
- no `document_events` row,
- no snapshot update,
- no version increment.

This task only changes browser rendering and client-side error routing around
existing backend error responses.

## Verification

- Static UI tests assert the validation failure rendering helpers and
  `SCHEMA_VALIDATION_FAILED` routing are served.
- Browser smoke should create a schema-bound document, attempt an invalid save,
  verify path-level validation diagnostics, and confirm replay/event count stay
  unchanged.
- Existing full test suite must remain green.
