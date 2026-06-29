# TASK_084_PLAN.md

## Objective

Harden schema-bound document mutation gates for persisted schema rows whose
`schema_json` parses as JSON but is not a valid JSON Schema document.

## Scope

- `POST /projects/{project_id}/documents`
- `PATCH /documents/{document_id}`
- `POST /documents/{document_id}/patch-preview`
- `POST /documents/{document_id}/restore`
- `POST /documents/{document_id}/rollback`
- `POST /documents/{document_id}/validate`

## Policy

- Normal schema creation still rejects invalid JSON Schema documents with
  `INVALID_JSON_SCHEMA`.
- If an existing persisted schema row is corrupt because `schema_json` is
  parseable JSON but fails `Draft202012Validator.check_schema`, schema-bound
  document mutation gates fail with structured `INTERNAL_ERROR` diagnostics:
  - `diagnostic_code: "SCHEMA_JSON_SCHEMA_INVALID"`
  - `schema_id`
  - `project_id`
  - `field: "schema_json"`
- The failure happens before any document event, snapshot, version, or
  lifecycle write.
- Patch preview and validate remain read-only and also leave documents/events
  unchanged.
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, comments,
  reviews, schema mutation endpoints, or complex path-level permissions.

## Verification

- Add service-level coverage for create, patch, patch-preview, validate,
  rollback, and restore against an invalid persisted schema row.
- Verify each failed operation leaves `document_events`, snapshots, versions,
  and lifecycle state unchanged.
- Run focused tests, related schema suites, and the full test suite.
