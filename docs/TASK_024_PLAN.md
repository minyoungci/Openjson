# TASK_024 Plan - Schema Usage API

## Goal

Add a read-only schema usage API that reports which documents are currently
bound to a schema and whether their latest snapshots validate against it.

This strengthens the JSON Schema registry foundation by making schema impact
inspectable without adding schema mutation or custom validation.

## Non-Goals

- No schema update, deactivate, or migration workflow.
- No automatic document rebinding.
- No custom project validation engine.
- No persistent validation result table.
- No document, schema, audit, or event mutation.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## API

`GET /schemas/{schema_id}/usage`

Query parameters:

- `include_deleted`: optional boolean, default `false`.
- `only_invalid`: optional boolean, default `false`.
- `limit`: optional page size, 1 through 100, default 50.
- `offset`: optional offset, default 0.

The endpoint requires project `document:validate` permission for the schema's
project. This matches the existing project validation report policy:
owner/admin/editor/reviewer may read validation diagnostics; viewer cannot.
Project-scoped API tokens may call it only for schemas in their own project and
only when the owning user has the required role.

## Response Shape

```json
{
  "schema_id": "schema_001",
  "project_id": "project_dev",
  "schema": {
    "id": "schema_001",
    "project_id": "project_dev",
    "name": "model-config",
    "version": "1",
    "file_pattern": "config/*.json",
    "is_active": true,
    "created_by": "user_dev",
    "created_at": "2026-06-27T00:00:00Z"
  },
  "status": "invalid",
  "summary": {
    "bound_documents": 2,
    "valid_documents": 1,
    "invalid_documents": 1,
    "deleted_documents": 0
  },
  "documents": [
    {
      "document_id": "doc_001",
      "project_id": "project_dev",
      "full_path": "config/model.json",
      "current_version": 2,
      "deleted_at": null,
      "validation": {
        "valid": false,
        "errors": [
          {
            "path": "/learning_rate",
            "message": "0.001 is less than the minimum of 0.01",
            "validator": "minimum",
            "expected": 0.01,
            "actual": 0.001
          }
        ],
        "warnings": []
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
    "include_deleted": false,
    "only_invalid": false
  }
}
```

## Data Model

No schema change.

The API reads `schemas` and `json_documents`, then runs JSON Schema Draft
2020-12 validation in memory against each bound latest snapshot. It does not
write validation rows, audit rows, document events, schemas, or snapshots.
TASK_040 later extends this read-only surface so malformed persisted latest
snapshot JSON is reported as a structured `json_syntax` validation failure.

## Tests

- Usage summarizes bound valid, invalid, and deleted documents.
- Document rows include metadata and validation result but not JSON content.
- `only_invalid=true` filters returned documents while preserving summary.
- `include_deleted=true` includes soft-deleted bound documents.
- Pagination reports `limit`, `offset`, `total`, and `has_more`.
- Missing schema and invalid pagination return standard errors.
- Read does not create document events, audit rows, or snapshot mutations.
- Owner/admin/editor/reviewer can read; viewer/non-member cannot.
- Project-scoped token follows project scope and owner role.
