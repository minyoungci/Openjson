# TASK_025 Plan - Schema Match Preview API

## Goal

Add a read-only project-scoped schema match preview API for document paths.

The API answers: "If I create a document at this `full_path` without an
explicit `schema_id`, which active file-pattern schema would bind?"

This makes TASK_002 file-pattern binding behavior inspectable before document
creation and helps callers avoid `AMBIGUOUS_SCHEMA_MATCH`.

## Non-Goals

- No document creation, schema binding mutation, or automatic rebinding.
- No schema update, deactivate, or priority rule.
- No custom validation engine.
- No persisted match cache or background job.
- No document event, audit event, schema, or snapshot mutation.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## API

`GET /projects/{project_id}/schema-matches?full_path=config/model.json`

Query parameters:

- `full_path`: required POSIX-style document path.

The endpoint requires project `schema:read` permission. It returns schema
metadata only, not full schema JSON and not document content.

Project-scoped API tokens may call it only for their own project.

## Response Shape

```json
{
  "project_id": "project_dev",
  "full_path": "config/model.json",
  "match_count": 1,
  "resolution": {
    "status": "matched",
    "schema_id": "schema_001"
  },
  "matches": [
    {
      "id": "schema_001",
      "project_id": "project_dev",
      "name": "model-config",
      "version": "1",
      "file_pattern": "config/*.json",
      "is_active": true,
      "created_by": "user_dev",
      "created_at": "2026-06-27T00:00:00Z"
    }
  ]
}
```

Resolution statuses:

- `no_match`: no active file-pattern schema matches `full_path`.
- `matched`: exactly one active file-pattern schema matches `full_path`.
- `ambiguous`: more than one active file-pattern schema matches `full_path`.

## Data Model

No schema change.

The API reads active project schemas with non-null `file_pattern` and applies
the same Python `fnmatch.fnmatch(full_path, file_pattern)` policy used during
document creation.

## Tests

- No match, one match, and ambiguous match statuses.
- Matching uses the same nested `fnmatch` behavior as document create.
- Returned rows include schema metadata but not schema JSON.
- Invalid or blank `full_path` is rejected with a standard error.
- Viewer can read; non-member cannot.
- Project-scoped API token can read only its own project.
- Read does not create document events, audit rows, documents, or schemas.
