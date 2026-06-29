# TASK_081_PLAN.md

## Objective

Harden the document patch preview boundary without adding new product surface.

## Scope

- `POST /documents/{document_id}/patch-preview`
- `preview_document_patch`

## Policy

- Patch preview is read-only, but it still requires the same document write
  permission as accepted patch mutations.
- Editors may preview a candidate patch when they can write the document.
- Reviewers, viewers, and non-members cannot preview candidate mutations.
- Patch preview only applies to active documents. Soft-deleted documents return
  `DOCUMENT_NOT_FOUND`.
- Patch preview must fail on malformed persisted latest snapshots with the same
  structured `SNAPSHOT_JSON_DECODE_FAILED` diagnostic used by core document
  mutation gates.
- Successful preview never inserts `document_events`.
- Successful preview never updates `json_documents.current_version`.
- Successful preview never updates `json_documents.current_snapshot_json`.
- Failed preview attempts also leave event logs, versions, and snapshots
  unchanged.
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, comments,
  reviews, schema mutation endpoints, or complex path-level permissions.

## Verification

- Add RBAC coverage for editor-allowed preview and reviewer/viewer/non-member
  denials.
- Add soft-deleted document denial coverage with history and replay preserved.
- Add malformed latest snapshot coverage for patch preview.
- Run focused tests, related suites, and the full test suite.
