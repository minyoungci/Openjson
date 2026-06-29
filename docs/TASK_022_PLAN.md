# TASK_022 Plan - Project Document Tree API

## Goal

Add a read-only project-scoped document tree API built from
`json_documents.full_path`.

This fills the MVP "folder-like document path" gap without adding a persisted
folder table or frontend UI.

## Non-Goals

- No UI file tree.
- No persisted `folders` table.
- No document move/rename endpoint.
- No path-level permission model.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No document event, audit event, or snapshot mutation.

## API

`GET /projects/{project_id}/document-tree`

Query parameters:

- `include_deleted`: optional boolean, default `false`.
- `path_prefix`: optional POSIX-style path prefix. When supplied, returned tree
  is rooted at that virtual folder prefix.

The endpoint requires project `document:read` permission. Project-scoped API
tokens may call it only for their own project.

## Response Shape

```json
{
  "project_id": "project_dev",
  "root": {
    "type": "folder",
    "name": "",
    "path": "",
    "document_count": 2,
    "children": [
      {
        "type": "folder",
        "name": "config",
        "path": "config",
        "document_count": 1,
        "children": [
          {
            "type": "document",
            "name": "model.json",
            "path": "config/model.json",
            "document": {
              "id": "doc_001",
              "project_id": "project_dev",
              "full_path": "config/model.json",
              "current_version": 2,
              "schema_id": null,
              "created_by": "user_dev",
              "created_at": "2026-06-27T00:00:00Z",
              "updated_at": "2026-06-27T00:00:00Z",
              "deleted_at": null
            }
          }
        ]
      }
    ]
  },
  "summary": {
    "document_count": 2,
    "folder_count": 1,
    "deleted_document_count": 0
  },
  "filters": {
    "include_deleted": false,
    "path_prefix": null
  }
}
```

## Data Model

No schema change.

Folders are virtual nodes derived from `full_path` segments at request time.
Documents remain the only persisted path-bearing rows.

## Tests

- Nested folders and root-level documents are represented in stable order.
- Tree responses include document metadata but not JSON content.
- Soft-deleted documents are hidden by default and included when requested.
- `path_prefix` roots the tree at a virtual folder.
- Invalid path prefix is rejected.
- Read does not create document events or mutate snapshots.
- Viewer can read; non-member cannot.
- Project-scoped API token can read only its own project.
