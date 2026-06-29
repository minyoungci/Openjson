# TASK_020 Plan - Project Replay Integrity API

## Goal

Add a read-only project-scoped replay integrity API.

The API lets an owner/admin verify that each exported/current document snapshot
matches the result of replaying its append-only `document_events` from the
beginning.

## Non-Goals

- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No document mutation, repair, auto-healing, or event rewriting.
- No audit-log mutation and no background job.
- No new storage table or migration.

## API

`GET /projects/{project_id}/integrity/replay`

Query parameters:

- `include_deleted`: optional boolean, default `true`.

The endpoint requires project `integrity:read` permission. TASK_020 grants this
permission only to project `owner` and `admin` roles. Project-scoped API tokens
may call it only when their owning user has that role in the same project.

## Response Shape

```json
{
  "project_id": "project_dev",
  "status": "ok",
  "include_deleted": true,
  "checked_documents": 1,
  "failure_count": 0,
  "documents": [
    {
      "document_id": "doc_001",
      "full_path": "config/model.json",
      "current_version": 2,
      "latest_event_version": 2,
      "event_count": 2,
      "deleted_at": null,
      "status": "ok",
      "replay_matches_latest": true
    }
  ],
  "failures": []
}
```

## Data Model

No schema change.

The API reads `json_documents` and `document_events`, runs replay in memory, and
returns a diagnostic report. It does not write `document_events`, `audit_log`,
snapshots, or repair data.

## Tests

- Healthy project reports `status=ok` across create, patch, rollback, delete,
  and restore sequences.
- Snapshot tampering produces `SNAPSHOT_REPLAY_MISMATCH`.
- Version tampering produces `VERSION_MISMATCH`.
- Soft-deleted documents are included by default and can be excluded with
  `include_deleted=false`.
- The read does not create document events or audit rows.
- Owner/admin can read; editor/viewer/non-member cannot.
- Project-scoped owner token can read only its own project.
- Viewer-owned project token is denied by RBAC.
