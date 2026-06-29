# TASK_040 Plan - Schema Usage Malformed JSON Diagnostics

## Goal

Extend malformed persisted JSON diagnostics to the schema usage API.

The schema usage API is a read-only diagnostic view over documents bound to a
schema. If a bound document's persisted latest snapshot is malformed because of
database corruption or manual tampering, the endpoint should report that
document as invalid instead of returning a server error.

## Non-Goals

- No document mutation, event mutation, snapshot repair, or event compaction.
- No schema mutation, rebinding, update, deactivate, or migration workflow.
- No persisted validation result table.
- No custom project validation engine.
- No UI work.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No complex path-level permission model.

## Behavior

For malformed `json_documents.current_snapshot_json` on a document bound to the
requested schema:

- the document remains included in schema usage results
- document `validation.valid` is `false`
- validation error uses `validator: "json_syntax"`
- validation error includes decoder details for `current_snapshot_json`
- top-level schema usage `status` is `invalid`
- HTTP response remains `200` for authorized diagnostic reads

## Data Model

No schema change.

The endpoint remains read-only. It reports malformed persisted latest snapshots
but does not repair snapshots, schemas, document events, or validation state.

## Tests

- Service-level schema usage reports malformed latest snapshot JSON as an
  invalid document without mutation.
- HTTP schema usage reports malformed latest snapshot JSON without returning a
  server error.
