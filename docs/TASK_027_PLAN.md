# TASK_027 Plan - Document Replay Integrity API

## Goal

Add a read-only document-scoped replay integrity API.

The API lets callers verify one document's core invariant without running a
project-wide integrity scan:

```text
Replay(document_events) == json_documents.current_snapshot_json
```

This is an operational diagnostic over the existing latest snapshot and
append-only event log. It does not mutate or repair data.

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

`GET /documents/{document_id}/integrity/replay`

The endpoint checks a single document, including soft-deleted documents.

Permission policy:

- Requires project `integrity:read` permission through the target document.
- In the current RBAC table, this means owner/admin only.
- Project-scoped API tokens may call it only for documents in their own
  project, and the token owner must still have `integrity:read`.

## Response Shape

```json
{
  "document_id": "doc_001",
  "project_id": "project_dev",
  "status": "ok",
  "failure_count": 0,
  "document": {
    "document_id": "doc_001",
    "project_id": "project_dev",
    "full_path": "config/model.json",
    "current_version": 3,
    "latest_event_version": 3,
    "event_count": 3,
    "deleted_at": null,
    "status": "ok",
    "replay_matches_latest": true
  },
  "failures": []
}
```

If the replay check fails, `status` is `failed`, `failure_count` is `1`, and
`failures` contains the same failed document report.

## Data Model

No schema change.

The API reads one `json_documents` row and its existing `document_events`.

## Tests

- OK result for create -> patch -> rollback -> delete -> restore sequence.
- Soft-deleted document remains checkable.
- Snapshot tampering is reported as `SNAPSHOT_REPLAY_MISMATCH`.
- Version tampering is reported as `VERSION_MISMATCH`.
- Owner/admin can read; editor/viewer/nonmember cannot.
- Missing actor and missing document return the standard error envelope.
- Project-scoped API token can read only its own project document integrity.
- Reads do not create document events, audit rows, or snapshot mutations.
