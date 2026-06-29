# TASK_088_PLAN.md

## Objective

Expose editor-facing reload diagnostics in `VERSION_CONFLICT` responses so
non-realtime shared JSON editing clients can recover from stale base versions
without guessing which document state to reload.

## Scope

- Enrich `VERSION_CONFLICT` details for accepted mutation and patch-preview
  paths that enforce document `base_version`.
- Include current document identity, reload endpoint, conflict policy, and the
  latest accepted document event metadata.
- Update the shared edit smoke script and tests to assert the richer conflict
  contract.

## Policy

- Conflicts remain rejected with HTTP 409 and `VERSION_CONFLICT`.
- Conflict responses do not create `document_events`, do not update snapshots,
  do not increment versions, and do not write audit rows.
- Latest event metadata is read from the append-only `document_events` table
  only to help clients explain and recover from the conflict.
- The client recovery path is still reload-and-resave through
  `GET /documents/{document_id}/editor-state`.
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, automatic
  merge/conflict resolution, or complex path-level permissions.

## Error Details Shape

```json
{
  "client_base_version": 1,
  "server_current_version": 2,
  "document_id": "doc_...",
  "project_id": "proj_...",
  "full_path": "config/shared-edit.json",
  "conflict_policy": "reject_stale_base_version",
  "reload": {
    "method": "GET",
    "endpoint": "/documents/doc_.../editor-state"
  },
  "latest_event": {
    "id": "evt_...",
    "event_type": "update",
    "base_version": 1,
    "result_version": 2,
    "actor_id": "user_...",
    "created_at": "2026-06-28T00:00:00Z"
  }
}
```

## Verification

- Assert conflict diagnostics on direct service-level patch and preview flows.
- Assert stale preview and stale save diagnostics in the two-actor
  non-realtime edit flow.
- Assert the live HTTP smoke script validates and reports the reload hint and
  latest event id.
- Run focused tests and the full test suite.
