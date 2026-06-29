# TASK_023 Plan - Project Activity Timeline API

## Goal

Add a read-only project-scoped activity timeline API that combines accepted
JSON document events with append-only operational audit log rows.

This gives project owners/admins one audit-first view of "what happened in this
project?" without changing the existing source-of-truth model.

## Non-Goals

- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No new mutation endpoint.
- No new storage table, persistent activity cache, or background job.
- No document event, audit event, or snapshot mutation.
- No complex path-level permission model.

## API

`GET /projects/{project_id}/activity`

Query parameters:

- `source`: optional, one of `all`, `document_events`, or `audit_log`.
  Default: `all`.
- `actor_id`: optional exact actor filter.
- `document_id`: optional exact document filter. For document events this
  filters by `document_events.document_id`; for audit rows this filters by
  `audit_log.document_id`.
- `limit`: optional page size, 1 through 100. Default: 50.
- `offset`: optional offset. Default: 0.

The endpoint requires project `audit:read` permission. This keeps operational
failure rows and token/member audit details restricted to owner/admin roles.
Project-scoped API tokens may call it only for their own project and only when
their owning user has the required role.

## Response Shape

```json
{
  "project_id": "project_dev",
  "items": [
    {
      "source": "document_event",
      "id": "event_001",
      "activity_type": "document.update",
      "actor_id": "user_dev",
      "document_id": "doc_001",
      "full_path": "config/model.json",
      "outcome": "success",
      "created_at": "2026-06-27T00:00:00Z",
      "document_event": {
        "event_type": "update",
        "base_version": 1,
        "result_version": 2,
        "changed_paths": ["/learning_rate"],
        "summary": "Updated document",
        "reason": null
      },
      "audit_log": null
    },
    {
      "source": "audit_log",
      "id": "audit_001",
      "activity_type": "project_member.add",
      "actor_id": "user_dev",
      "document_id": null,
      "full_path": null,
      "outcome": "success",
      "created_at": "2026-06-27T00:00:01Z",
      "document_event": null,
      "audit_log": {
        "target_type": "project_member",
        "target_id": "user_002",
        "error_code": null,
        "details": {}
      }
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 2,
    "has_more": false
  },
  "filters": {
    "source": "all",
    "actor_id": null,
    "document_id": null
  }
}
```

## Data Model

No schema change.

The API reads `document_events` joined to `json_documents` and reads
`audit_log`. It merges the two append-only streams in memory for the requested
project.

## Tests

- Activity includes document events and audit log rows in newest-first order.
- Activity rows include document metadata but not document content.
- Reads do not create document events, audit rows, or snapshot mutations.
- `source`, `actor_id`, and `document_id` filters work.
- Pagination reports `limit`, `offset`, `total`, and `has_more`.
- Invalid source, invalid pagination, blank actor/document filters, and
  cross-project document filters are rejected.
- Owner/admin can read; editor/viewer/non-member cannot.
- Project-scoped owner/admin token can read only its own project.
- Viewer-owned token is denied by RBAC.
