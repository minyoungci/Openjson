# TASK_083_PLAN.md

## Objective

Harden read-only schema diagnostics for persisted schema rows whose
`schema_json` parses as JSON but is not a valid JSON Schema document.

## Scope

- `GET /schemas/{schema_id}`
- `GET /projects/{project_id}/schemas`
- `GET /schemas/{schema_id}/usage`
- `GET /projects/{project_id}/validation-report`

## Policy

- Normal schema creation still rejects invalid JSON Schema documents with
  `INVALID_JSON_SCHEMA`.
- If a persisted schema row is corrupt because `schema_json` is parseable JSON
  but fails `Draft202012Validator.check_schema`, read-only diagnostic surfaces
  must not crash or mutate data.
- Schema metadata responses include `schema_json_error` with
  `diagnostic_code: "SCHEMA_JSON_SCHEMA_INVALID"`.
- Schema usage and project validation report mark affected documents invalid
  with `validator: "schema_json_invalid"`.
- Schema usage and project validation report remain read-only:
  - no `document_events`
  - no snapshot changes
  - no version changes
  - no audit rows
  - no schema repair
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, comments,
  reviews, schema mutation endpoints, or complex path-level permissions.

## Verification

- Add schema usage coverage for invalid persisted JSON Schema diagnostics.
- Add schema metadata, HTTP schema usage, and project validation report coverage
  for the same diagnostic.
- Run focused tests, related schema diagnostic suites, and the full test suite.
