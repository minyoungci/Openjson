# TASK_001 Baseline

This document records the approved TASK_001 and TASK_001_HARDENING implementation policy.

## Scope

TASK_001 is the versioned JSON document foundation. It proves that JSON documents can be created, updated, soft-deleted, restored, rolled back, diffed, and reconstructed from append-only events.

Do not add realtime collaboration, comments, review workflow, Git integration, AI features, branching, pull requests, WebSocket, offline sync, merge/conflict auto-resolution, complex path-level permission, or UI work to this baseline.

## JSON Patch Policy

The MVP supports only these JSON Patch-like operations:

- `add`
- `replace`
- `remove`

These operations are intentionally excluded from TASK_001 and TASK_002:

- `move`
- `copy`
- `test`

Unsupported operations return `UNSUPPORTED_PATCH_OPERATION`.

Accepted update patches must change the canonical JSON snapshot. Semantic
no-op patches return `PATCH_APPLY_FAILED` and create no event.

## Canonical Document Root Policy

Canonical JSON document content must be either:

- object
- array

Scalar roots such as string, number, boolean, and null are rejected even though they are valid JSON values. This keeps the workspace aligned with path-level validation, diff, rollback, comments, review, and future schema binding.

## Diff Error Policy

Version-to-version diff reconstructs both snapshots from the document event log and performs recursive JSON path comparison.

Diff error codes:

- `INVALID_VERSION_RANGE`: `from_version` or `to_version` is invalid, or `from_version > to_version`
- `DOCUMENT_VERSION_NOT_FOUND`: requested version does not exist in the document event log

## Rollback Policy

Rollback is snapshot-based in TASK_001.

The service reconstructs the target version from events, then records a new `rollback` event whose patch replaces the document root with the target snapshot.

Rollback targets must be older than the request `base_version`. Requests with
`target_version >= base_version` return `INVALID_VERSION_RANGE` and create no
event.

Rollback must never delete or rewrite existing events.

## Event Log Policy

`document_events` is append-only.

SQLite enforces this with triggers:

- `trg_document_events_no_update`
- `trg_document_events_no_delete`

Every accepted mutation must create a document event. Failed mutation attempts must not create events.

## Snapshot/Event Consistency

The latest snapshot is for fast access. The append-only event log is for trust, audit, diff, blame, and rollback.

Critical invariant:

```text
Replaying document_events from the beginning must reconstruct json_documents.current_snapshot_json exactly.
```

This invariant must hold across create, patch, delete, restore, rollback, and mixed sequences.

## Transaction Policy

For patch, delete, restore, and rollback:

- patch/replay candidate generation happens before event insert
- event insert and snapshot update happen inside the same `BEGIN IMMEDIATE` transaction
- if patch application fails, no event is inserted
- if event insert fails, snapshot is not updated
- if snapshot update fails, inserted event is rolled back
- delete event and `deleted_at` marker are committed or rolled back together
- rollback event and snapshot replacement are committed or rolled back together

## Storage Policy

TASK_001 uses SQLite for local MVP and test execution.

Before scaling workspace search, JSONB indexing, or broader collaboration features, PostgreSQL migration planning should be handled separately.
