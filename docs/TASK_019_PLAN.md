# TASK_019 Plan - Project Export Archive

## Goal

Add a read-only project export archive API that returns the current project
metadata, schemas, document snapshots, and document event history in one JSON
payload.

The purpose is auditability and portability of the event/snapshot foundation,
not Git integration or binary archive generation.

## Non-Goals

- No Git import/export integration.
- No branch, pull request, release tag, or merge workflow.
- No realtime collaboration, WebSocket, offline sync, or AI features.
- No UI work.
- No physical file storage, ZIP archive, object storage, or background job.
- No persistent export table.
- No document mutation, audit mutation, or document event write.

## API

`GET /projects/{project_id}/export`

Query parameters:

- `include_deleted`: optional boolean, default `false`.
- `include_comments`: optional boolean, default `false`.
- `include_reviews`: optional boolean, default `false`.
- `include_audit_log`: optional boolean, default `false`.

The endpoint requires project `export:read` permission. TASK_019 grants this
permission only to project `owner` and `admin` roles. Project-scoped API tokens
may call it only when their owning user has that role in the same project.

## Response Shape

```json
{
  "format_version": "openjson.project_export.v1",
  "exported_at": "2026-06-27T00:00:00Z",
  "project": {
    "id": "project_dev",
    "workspace_id": "workspace_dev",
    "name": "Dev Project"
  },
  "workspace": {
    "id": "workspace_dev",
    "name": "Dev Workspace"
  },
  "options": {
    "include_deleted": false,
    "include_comments": false,
    "include_reviews": false,
    "include_audit_log": false
  },
  "schemas": [],
  "documents": [
    {
      "id": "doc_001",
      "full_path": "config/model.json",
      "current_version": 2,
      "content": {"learning_rate": 0.001},
      "events": []
    }
  ],
  "comments": [],
  "reviews": [],
  "audit_log": [],
  "integrity": {
    "status": "ok",
    "replay_consistent": true,
    "event_chain_consistent": true,
    "document_count": 1,
    "document_event_count": 2,
    "documents": [
      {
        "document_id": "doc_001",
        "current_version": 2,
        "event_count": 2,
        "replay_matches_latest": true,
        "event_chain_status": "ok",
        "event_chain_failure_count": 0
      }
    ],
    "checks": {
      "replay": {
        "status": "ok"
      },
      "event_chain": {
        "status": "ok"
      }
    }
  }
}
```

## Data Model

No schema change.

The API reads existing tables and computes replay consistency from exported
document events. It does not insert into `document_events`, `audit_log`, or any
other table.

## Tests

- Export includes project/workspace metadata, schemas, current snapshots, and
  document event history.
- Export reports replay consistency and event-chain integrity for each exported
  document.
- Export read does not create document events or audit rows.
- Soft-deleted documents are hidden by default and included with
  `include_deleted=true`.
- Optional comments, reviews, and audit log sections are included only when
  requested.
- Owner/admin can export; editor/viewer/non-member cannot.
- Project-scoped owner token can export only its own project.
- Viewer-owned project token is denied by RBAC.
