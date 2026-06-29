# TASK_038 Plan - Validation Report Malformed JSON Diagnostics

## Goal

Extend TASK_037 malformed persisted JSON diagnostics to the project validation
report API.

The validation report is a read-only diagnostic surface over latest snapshots,
schema validation, replay consistency, and event-chain metadata. It should not
return a server error when a persisted document snapshot or event JSON field is
malformed. Instead, it should return a normal validation report whose
validation and integrity sections identify the corruption.

TASK_039 applies the same diagnostic policy to the project export archive API.

## Non-Goals

- No document mutation, event mutation, snapshot repair, or event compaction.
- No migration repair, migration deletion, or schema rewrite.
- No new persisted validation or integrity table.
- No schema registry update/deactivate API.
- No UI work.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No complex path-level permission model.

## Behavior

For malformed `json_documents.current_snapshot_json`:

- document `validation.valid` is `false`
- validation error uses `validator: "json_syntax"`
- document integrity reports replay and event-chain failure
- top-level report `integrity.status` is `failed`

For malformed document event JSON fields:

- schema validation still runs against the latest snapshot when possible
- document integrity reports replay and event-chain failure
- top-level report `integrity.status` is `failed`
- HTTP response remains `200` for authorized diagnostic reads

## Data Model

No schema change.

The validation report now uses the integrity service's row-based report
builders so event JSON parsing failures are reported consistently with the
operational integrity CLI.

## Tests

- Service-level validation report returns structured validation and integrity
  failure for malformed latest snapshot JSON.
- HTTP validation report returns structured integrity failure for malformed
  document event JSON without returning a server error.
