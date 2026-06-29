# TASK_082_PLAN.md

## Objective

Harden the document validation API response for editor-facing clients.

## Scope

- `POST /documents/{document_id}/validate`
- `validate_document`

## Policy

- Document validation remains a read-only trust surface.
- Validation does not create `document_events`.
- Validation does not update `json_documents.current_version`.
- Validation does not update `json_documents.current_snapshot_json`.
- Validation does not persist validation results.
- The response includes the document context that identifies the snapshot being
  validated:
  - `document_id`
  - `project_id`
  - `full_path`
  - `current_version`
  - `deleted_at`
  - `schema_id`
- Bound, invalid, and unbound validation responses use the same context shape.
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, comments,
  reviews, schema mutation endpoints, or complex path-level permissions.

## Verification

- Add service-level validation tests for context fields on bound, invalid, and
  unbound documents.
- Add HTTP bearer-token validation tests for the same response context.
- Verify validation still leaves event logs, versions, and snapshots unchanged.
- Run focused tests, related validation suites, and the full test suite.
