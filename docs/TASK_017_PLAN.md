# TASK_017 Plan - Project Document Event Feed

## Goal

Add a read-only project-scoped feed over accepted JSON document events.

The API answers "what document mutations happened recently in this project?"
without requiring a caller to open each document history endpoint one by one.

## Non-Goals

- No realtime collaboration.
- No WebSocket or offline sync.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No new permission model or path-level permissions.
- No mutation endpoint and no new document event type.

## API

`GET /projects/{project_id}/document-events`

Query parameters:

- `event_type`: optional exact match for `create`, `update`, `delete`, `restore`, or `rollback`.
- `actor_id`: optional exact event actor filter.
- `document_id`: optional exact document filter, scoped to the project.
- `changed_path`: optional exact JSON Pointer path match against stored `changed_paths`.
- `limit`: optional page size, 1 through 100, default 50.
- `offset`: optional offset, default 0.

The endpoint requires project `document:read` permission. Project-scoped API
tokens may call it only for their own project.

## Response Shape

```json
{
  "project_id": "project_dev",
  "events": [
    {
      "id": "event_001",
      "document_id": "doc_001",
      "project_id": "project_dev",
      "full_path": "config/model.json",
      "actor_id": "user_dev",
      "validation_schema_id": null,
      "event_type": "update",
      "base_version": 1,
      "result_version": 2,
      "patch": [],
      "inverse_patch": [],
      "changed_paths": ["/learning_rate"],
      "before_values": [],
      "after_values": [],
      "summary": "Updated document",
      "reason": null,
      "created_at": "2026-06-27T00:00:00Z"
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 1,
    "has_more": false
  },
  "filters": {
    "event_type": null,
    "actor_id": null,
    "document_id": null,
    "changed_path": null
  }
}
```

## Data Model

No schema change.

The endpoint reads `document_events` joined to `json_documents` by document id.
It does not insert audit rows, document events, or any other data.

## Tests

- Feed returns events across multiple project documents.
- Feed is newest-first and includes document path metadata.
- Read does not mutate document events or snapshots.
- Filters cover event type, actor, document id, root path, and nested changed path.
- Pagination reports `limit`, `offset`, `total`, and `has_more`.
- Invalid pagination, invalid event type, and invalid JSON Pointer are rejected.
- Viewer can read; non-member is denied.
- A document id from another project is rejected as `DOCUMENT_NOT_FOUND`.
- HTTP route and project API token scope are verified.
