# TASK_026 Plan - Document Event Detail API

## Goal

Add a read-only document event detail API.

The API lets callers open a single append-only `document_events` row by id,
inspect the stored patch/inverse/before/after values, and optionally include
the replay-reconstructed snapshots before and after the event.

This strengthens the event-log-as-source-of-trust model without adding mutation
or a new storage table.

## Non-Goals

- No event mutation, event rewriting, repair, or compaction.
- No document mutation, audit mutation, schema mutation, or snapshot write.
- No new persisted event detail table or cache.
- No UI diff view.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No complex path-level permission model.

## API

`GET /documents/{document_id}/events/{event_id}`

Query parameters:

- `include_snapshots`: optional boolean, default `false`.

The endpoint requires project `document:read` permission through the target
document. It allows reads for soft-deleted documents, matching existing
document history policy.

Project-scoped API tokens may call it only for documents in their own project.

## Response Shape

```json
{
  "document_id": "doc_001",
  "project_id": "project_dev",
  "full_path": "config/model.json",
  "current_version": 3,
  "deleted_at": null,
  "event": {
    "id": "evt_002",
    "document_id": "doc_001",
    "actor_id": "user_dev",
    "validation_schema_id": null,
    "event_type": "update",
    "base_version": 1,
    "result_version": 2,
    "patch": [
      {"op": "replace", "path": "/learning_rate", "value": 0.0005}
    ],
    "inverse_patch": [
      {"op": "replace", "path": "/learning_rate", "value": 0.001}
    ],
    "changed_paths": ["/learning_rate"],
    "before_values": [
      {"path": "/learning_rate", "exists": true, "value": 0.001}
    ],
    "after_values": [
      {"path": "/learning_rate", "exists": true, "value": 0.0005}
    ],
    "summary": "Updated document",
    "reason": null,
    "created_at": "2026-06-27T00:00:00Z"
  },
  "snapshots": {
    "included": true,
    "before": {"learning_rate": 0.001},
    "after": {"learning_rate": 0.0005}
  }
}
```

When `include_snapshots=false`, the `snapshots` object is:

```json
{
  "included": false,
  "before": null,
  "after": null
}
```

## Data Model

No schema change.

The API reads `json_documents` and `document_events`. When snapshots are
requested, it reconstructs the before and after states from the existing
append-only event log.
TASK_041 later extends this read-only surface so malformed persisted event JSON
fields are returned as structured `json_errors`, and snapshot reconstruction
failures are reported under `snapshots.error`.

## Tests

- Event detail returns the exact stored patch, inverse patch, changed paths,
  before values, and after values.
- `include_snapshots=true` reconstructs before and after snapshots from replay.
- Create, update, delete, rollback, and restore events can be inspected.
- Soft-deleted document events remain readable.
- Event id from another document is rejected as `DOCUMENT_NOT_FOUND`.
- Viewer can read; non-member cannot.
- Project-scoped API token can read only its own project document events.
- Reads do not create document events, audit rows, or snapshot mutations.
