# TASK_063 Plan - Multi-Operation Patch Atomicity

## Goal

Pin down atomic behavior for multi-operation document update patches.

A JSON Patch-like update can contain several operations. If any operation in
the sequence fails, the whole update must be rejected. Earlier operations in
that failed request must not create an event, change the latest snapshot, or
increment the document version.

## Non-Goals

- No new patch operation support.
- No JSON Patch move, copy, or test support.
- No semantic merge or conflict auto-resolution.
- No DB schema change.
- No document editor UI.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Covered Endpoint

- `PATCH /documents/{document_id}`

## Behavior

For user-submitted document update patches:

- operations are applied to an isolated candidate snapshot
- if a later operation fails, the whole patch returns `PATCH_APPLY_FAILED`
- no `document_events` row is inserted for the failed patch
- `json_documents.current_snapshot_json` remains unchanged
- `json_documents.current_version` remains unchanged
- the document remains replay-consistent with its latest accepted event

## Data Model

No schema change.

This task only adds regression coverage for the existing candidate-snapshot
patch pipeline and transaction boundary.

## Tests

- Service-level multi-operation patch with an early valid operation and later
  invalid operation rejects without event, snapshot, or version mutation.
- HTTP multi-operation patch with an early valid operation and later invalid
  operation rejects with the standard error envelope and no partial mutation.
