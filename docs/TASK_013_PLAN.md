# TASK_013 Plan: Project Document Listing Baseline

TASK_013 adds a minimal project-scoped document listing endpoint.

The goal is to let clients browse a project's JSON documents without loading
every latest snapshot body.

This task does not add UI work, realtime collaboration, WebSocket, Git
integration, branching, pull requests, AI features, offline sync, full-text
search indexing, folder tree materialization, export/import, custom validation,
or complex path-level permissions.

## Scope

- Add `GET /projects/{project_id}/documents`.
- Enforce existing project RBAC with `document:read`.
- Return metadata only by default, not document content.
- Exclude soft-deleted documents by default.
- Support optional `include_deleted`.
- Support optional `path_prefix` filtering on `full_path`.
- Support optional `q` filtering on `full_path`.
- Support simple `limit` and `offset` pagination.

## Response Shape

```json
{
  "project_id": "project_001",
  "documents": [
    {
      "id": "doc_001",
      "project_id": "project_001",
      "full_path": "config/model.json",
      "current_version": 3,
      "schema_id": null,
      "created_by": "user_001",
      "created_at": "2026-06-27T00:00:00Z",
      "updated_at": "2026-06-27T00:00:00Z",
      "deleted_at": null
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 1,
    "has_more": false
  },
  "filters": {
    "include_deleted": false,
    "path_prefix": null,
    "q": null
  }
}
```

## Non-Goals

- No JSON content in list rows.
- No project-wide JSON key/value search.
- No dedicated search index.
- No folder tree API yet.
- No path-level permission rules.
- No document mutation or event creation.

## Tests

- Active documents list in stable `full_path` order.
- Metadata response excludes `content`.
- `path_prefix` and `q` filters work on `full_path`.
- Soft-deleted documents are hidden by default and visible with
  `include_deleted=true`.
- Pagination returns `total` and `has_more`.
- Invalid pagination and path filters return standard errors.
- Viewer can list; non-member cannot.
- API token can list its project and cannot list another project.
- Listing does not create `document_events` or mutate snapshots.
