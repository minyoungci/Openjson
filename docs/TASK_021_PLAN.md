# TASK_021 Plan - Project Validation Report API

## Goal

Add a read-only project-scoped validation report API over latest document
snapshots.

The API summarizes which project documents are schema-bound, unbound, valid,
or invalid, and returns per-document JSON Schema validation errors.

## Non-Goals

- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No custom project validation engine.
- No schema update/deactivate endpoint.
- No document mutation, auto-fix, event write, or audit write.
- No persistent validation result table.

## API

`GET /projects/{project_id}/validation-report`

Query parameters:

- `include_deleted`: optional boolean, default `false`.
- `only_invalid`: optional boolean, default `false`.

The endpoint requires project `document:validate` permission. This follows the
existing document-level validation endpoint: owner, admin, editor, and reviewer
roles may validate; viewer cannot.

## Response Shape

```json
{
  "project_id": "project_dev",
  "status": "invalid",
  "include_deleted": false,
  "only_invalid": false,
  "summary": {
    "checked_documents": 2,
    "valid_documents": 1,
    "invalid_documents": 1,
    "unbound_documents": 0,
    "deleted_documents": 0
  },
  "integrity": {
    "status": "ok",
    "replay_consistent": true,
    "event_chain_consistent": true,
    "checks": {
      "replay": {
        "status": "ok"
      },
      "event_chain": {
        "status": "ok"
      }
    }
  },
  "documents": [
    {
      "document_id": "doc_001",
      "full_path": "config/model.json",
      "current_version": 2,
      "deleted_at": null,
      "schema_id": "schema_001",
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
      },
      "integrity": {
        "replay_status": "ok",
        "replay_matches_latest": true,
        "event_chain_status": "ok",
        "event_chain_failure_count": 0
      }
    }
  ]
}
```

## Data Model

No schema change.

The API reads `json_documents`, bound `schemas`, and `document_events`, then
runs JSON Schema Draft 2020-12 validation and event-log integrity diagnostics
in memory. It does not store validation or integrity results.

## Tests

- Bound valid and invalid documents are reported.
- Unbound documents produce a warning and are counted separately.
- `only_invalid=true` filters valid and unbound documents out of the returned
  document list while preserving summary counts.
- Soft-deleted documents are hidden by default and included with
  `include_deleted=true`.
- JSON Pointer error paths preserve escaping.
- Read does not create document events or audit rows.
- Report includes replay and event-chain integrity context.
- `only_invalid=true` does not hide top-level integrity failures.
- Owner/admin/editor/reviewer can read; viewer/non-member cannot.
- Project-scoped token follows the owning user's RBAC and cannot cross project
  scope.
