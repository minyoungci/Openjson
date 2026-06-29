# TASK_016 Plan: Soft-Deleted Document Restore API

TASK_016 adds a minimal restore API for soft-deleted JSON documents.

The goal is to make deletion reversible without rewriting or deleting document
history. Restore is recorded as a new `document_events` row and clears
`json_documents.deleted_at` only when the original path is available.

This task does not add UI work, realtime collaboration, WebSocket, Git
integration, branching, pull requests, AI features, offline sync, physical
deletion, retention policy, export/import, or complex path-level permissions.

## Scope

- Add `POST /documents/{document_id}/restore`.
- Require `actor_id` and `base_version`.
- Enforce a new project permission, `document:restore`, granted to owner/admin
  only.
- Restore only soft-deleted documents.
- Reject restore when another active document already uses the same
  `(project_id, full_path)`.
- Validate the restored snapshot against the bound schema when present.
- Insert a new `event_type=restore` document event.
- Clear `deleted_at` and increment `current_version` in the same transaction.
- Preserve all previous events.
- Keep replay consistency: replaying events still reconstructs
  `current_snapshot_json`.

## Response Shape

```json
{
  "id": "doc_001",
  "project_id": "project_001",
  "full_path": "config/model.json",
  "current_version": 3,
  "deleted_at": null,
  "previous_version": 2,
  "validation": {
    "valid": true,
    "errors": [],
    "warnings": []
  }
}
```

## Non-Goals

- No physical undelete from external storage.
- No restoring into a new path.
- No admin retention policy.
- No workspace/project restore.
- No path-level restore.
- No field-level undo.

## Tests

- Restore creates a new `restore` event and preserves create/delete history.
- Restore clears `deleted_at`, increments version by one, and makes
  `GET /documents/{document_id}` work again.
- Restore keeps replay result equal to latest snapshot.
- Wrong `base_version` creates no event and leaves `deleted_at` unchanged.
- Restoring an active document is rejected without event writes.
- Restoring with an active path conflict is rejected without event writes.
- Owner/admin can restore; editor/viewer/non-member cannot.
- Project-scoped API token can restore within its project and cannot restore
  another project.
