# TASK_014 Plan: Document Version Snapshot API

TASK_014 adds a minimal version snapshot read API backed by `document_events`
replay.

The goal is to let clients inspect the exact JSON document content at a known
version without mutating document state or relying on the latest snapshot.

This task does not add UI work, realtime collaboration, WebSocket, Git
integration, branching, pull requests, AI features, offline sync, custom
validation, compacted snapshot storage, export/import, or complex path-level
permissions.

## Scope

- Add `GET /documents/{document_id}/history/{version}`.
- Enforce existing project RBAC with `document:read`.
- Reconstruct the requested version from append-only `document_events`.
- Return the reconstructed `content` and the event that produced the version.
- Allow reads for soft-deleted documents, matching the existing history policy.
- Reject non-positive versions with `INVALID_VERSION_RANGE`.
- Return `DOCUMENT_VERSION_NOT_FOUND` when the version is absent from the event
  log.

## Response Shape

```json
{
  "document_id": "doc_001",
  "project_id": "project_001",
  "full_path": "config/model.json",
  "version": 2,
  "current_version": 3,
  "is_latest": false,
  "deleted_at": null,
  "content": {
    "learning_rate": 0.0005
  },
  "event": {
    "id": "evt_002",
    "event_type": "update",
    "base_version": 1,
    "result_version": 2
  }
}
```

## Non-Goals

- No event mutation.
- No snapshot mutation.
- No physical snapshot table.
- No path-level history endpoint yet.
- No field-level blame endpoint yet.
- No compacted snapshot acceleration yet.

## Tests

- Version snapshot is reconstructed from events after create and patch.
- Rollback and delete sequences can be inspected by version.
- Soft-deleted documents keep version snapshot access.
- Missing/invalid versions return standard errors.
- Viewer can read version snapshots; non-member cannot.
- API token can read its project document version and cannot read another
  project.
- Version snapshot reads do not create `document_events` or mutate latest
  snapshots.
