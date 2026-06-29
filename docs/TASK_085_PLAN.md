# TASK_085_PLAN.md

## Objective

Add a read-only editor-facing document state API that lets a JSON editor client
load the current snapshot, required base version, actor capabilities, bound
schema metadata, optional validation result, and recent document events in one
request.

## Scope

- `GET /documents/{document_id}/editor-state`
- Service-level read model composition in `document_service`.
- Tests for owner/editor-style load, viewer capability limits, optional
  validation omission, soft-delete rejection, invalid bound schema diagnostics,
  API token project scope, and route registration.

## Policy

- This endpoint is read-only. It does not create `document_events`, update
  snapshots, increment versions, write audit rows, or persist validation state.
- It is for active document editing state only; soft-deleted documents are not
  editor-loadable through this endpoint.
- It requires document read permission.
- Actor capabilities are derived from existing project RBAC roles.
- Validation is optional. If requested but the actor lacks validate permission,
  the endpoint returns `validation.available = false` with
  `reason = "permission_denied"` instead of failing the whole editor-state
  load.
- If a bound schema row is malformed or parseable but invalid as a JSON Schema,
  schema metadata includes existing structured diagnostics and validation is
  marked unavailable with `reason = "schema_unavailable"`.
- `required_base_version` is the version clients must send to accepted patch
  and patch-preview endpoints.
- The endpoint explicitly reports `conflict_policy =
  "reject_stale_base_version"` and supported patch operations `add`,
  `replace`, and `remove`.
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, automatic
  merge/conflict resolution, or complex path-level permissions.

## Verification

- Add `tests/test_document_editor_state.py`.
- Verify editor-state reads do not mutate event counts, snapshots, versions, or
  replay consistency.
- Verify project-scoped API tokens can access same-project document
  editor-state and cannot access another project's document state.
- Run focused tests, related document/RBAC/API-token suites, and the full test
  suite.
