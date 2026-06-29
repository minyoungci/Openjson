# TASK_028 Plan - Document Event Chain Integrity API

## Goal

Add a read-only document event chain integrity API.

Replay integrity proves the final snapshot can be reconstructed. This task adds
a stricter diagnostic for the event log itself:

- event versions form a contiguous `base_version -> result_version` chain
- first event starts at version `0` and creates version `1`
- event type is one of the supported document mutation event types
- stored `changed_paths`, `inverse_patch`, `before_values`, and `after_values`
  match what replay observes while applying each event
- the final replayed state still equals the latest snapshot

This strengthens trust in `document_events` as the auditable source of truth.

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

`GET /documents/{document_id}/integrity/events`

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
  "full_path": "config/model.json",
  "status": "ok",
  "event_count": 3,
  "checked_events": 3,
  "failure_count": 0,
  "checks": {
    "version_chain": "ok",
    "event_types": "ok",
    "event_metadata": "ok",
    "replay_matches_latest": "ok"
  },
  "failures": []
}
```

Failures are returned as diagnostic objects rather than HTTP errors unless the
caller lacks access or the document does not exist.

## Data Model

No schema change.

The API reads one `json_documents` row and its existing `document_events`.

## Tests

- OK result for create -> patch -> rollback -> delete -> restore sequence.
- Soft-deleted document remains checkable.
- Version gap or wrong base/result version is reported.
- Stored before/after value metadata mismatch is reported even when final
  replay still matches the latest snapshot.
- Snapshot replay mismatch is still reported.
- Owner/admin can read; editor/viewer/nonmember cannot.
- Project-scoped API token can read only its own project document event-chain
  integrity.
- Reads do not create document events, audit rows, or snapshot mutations.
