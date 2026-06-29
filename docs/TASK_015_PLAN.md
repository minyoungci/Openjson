# TASK_015 Plan: Path History and Blame Baseline

TASK_015 adds minimal read-only path history and blame APIs backed by
`document_events`.

The goal is to answer: "Who last changed this JSON Pointer path, when, and
what changed?"

This task does not add UI work, realtime collaboration, WebSocket, Git
integration, branching, pull requests, AI features, offline sync, search index
infrastructure, field-level undo, or complex path-level permissions.

## Scope

- Add `GET /documents/{document_id}/path-history?path=/json/pointer`.
- Add `GET /documents/{document_id}/blame?path=/json/pointer`.
- Enforce existing project RBAC with `document:read`.
- Compute path history by replaying each event and comparing the target path
  before and after the event.
- Include create/update/rollback events when the requested path value changes.
- Allow reads for soft-deleted documents, matching existing history policy.
- Support root path with `path=`.
- Validate JSON Pointer syntax and return `INVALID_REQUEST` for malformed
  paths.
- Do not create `document_events`, audit rows, or snapshot writes.

## Response Shape

```json
{
  "document_id": "doc_001",
  "project_id": "project_001",
  "full_path": "config/model.json",
  "path": "/learning_rate",
  "current_version": 3,
  "deleted_at": null,
  "latest": {
    "exists": true,
    "value": 0.001
  },
  "changes": [
    {
      "event_id": "evt_002",
      "event_type": "update",
      "actor_id": "user_001",
      "base_version": 1,
      "result_version": 2,
      "before": {
        "exists": true,
        "value": 0.001
      },
      "after": {
        "exists": true,
        "value": 0.0005
      }
    }
  ],
  "blame": {
    "event_id": "evt_002",
    "actor_id": "user_001",
    "result_version": 2
  }
}
```

`GET /documents/{document_id}/blame` returns only the `blame` object plus the
current path value metadata.

## Non-Goals

- No path-level permission enforcement.
- No text or UI diff.
- No query over all documents.
- No dedicated search index.
- No field-level inverse patch rollback.
- No persisted blame cache.

## Tests

- Path history includes create, update, and rollback when the path value
  changes.
- Unrelated events are excluded.
- Parent object replacement is detected for child paths.
- JSON Pointer escaping works.
- Missing paths return an empty history and `latest.exists=false`.
- Soft-deleted documents retain path history access.
- Viewer can read; non-member cannot.
- API token scope is enforced.
- Invalid path syntax returns `INVALID_REQUEST`.
- Path history/blame reads do not create events or mutate snapshots.
