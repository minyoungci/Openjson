# TASK_029 Plan - Project Event Chain Integrity API

## Goal

Add a read-only project-scoped event chain integrity API.

TASK_028 checks one document's event chain. This task lets operators scan every
document in a project and detect event-log defects without opening documents
one by one.

The API checks each document for:

- contiguous `base_version -> result_version` event chain
- supported event types
- stored `changed_paths`, `inverse_patch`, `before_values`, and `after_values`
  matching replay-observed metadata
- final event-chain replay matching the latest snapshot

This strengthens the append-only event log as the auditable source of truth at
project scope.

## Non-Goals

- No document mutation, event mutation, snapshot repair, event compaction, or
  audit mutation.
- No new persisted integrity table or cache.
- No background checker or scheduler.
- No UI work.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No complex path-level permission model.

## API

`GET /projects/{project_id}/integrity/events`

Query parameters:

- `include_deleted`: optional boolean, default `true`.

Permission policy:

- Requires project `integrity:read`.
- In the current RBAC table, this means owner/admin only.
- Project-scoped API tokens may call it only for their own project, and the
  token owner must still have `integrity:read`.

## Response Shape

```json
{
  "project_id": "project_dev",
  "status": "ok",
  "include_deleted": true,
  "checked_documents": 2,
  "failure_count": 0,
  "documents": [
    {
      "document_id": "doc_001",
      "project_id": "project_dev",
      "full_path": "config/model.json",
      "status": "ok",
      "failure_count": 0,
      "checks": {
        "version_chain": "ok",
        "event_types": "ok",
        "event_metadata": "ok",
        "replay_matches_latest": "ok"
      },
      "failures": []
    }
  ],
  "failures": []
}
```

`failure_count` counts failed documents. Per-document reports retain their own
per-event failure counts.

## Data Model

No schema change.

The API reads project `json_documents` rows and their existing
`document_events`.

## Tests

- OK result for a project with active and restored documents.
- `include_deleted=false` excludes soft-deleted documents.
- Version-chain defects and metadata defects are reported per document.
- Snapshot replay mismatch is reported per document.
- Owner/admin can read; editor/viewer/nonmember cannot.
- Project-scoped API token can read only its own project event-chain integrity.
- Reads do not create document events, audit rows, or snapshot mutations.
