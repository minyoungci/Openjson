# TASK_077_PLAN.md

## Objective

Harden rollback version range policy so rollback cannot create no-op or
forward-looking audit events.

## Policy

- Rollback remains snapshot-based and append-only.
- A rollback target must be older than the caller's `base_version`.
- `target_version >= base_version` is rejected with `INVALID_VERSION_RANGE`.
- Rejected rollback requests must not insert a `document_events` row.
- Rejected rollback requests must not update `json_documents.current_version`
  or `json_documents.current_snapshot_json`.
- Valid rollback still creates a new `event_type = rollback` event and updates
  the latest snapshot in the same transaction.
- This task does not add realtime collaboration, UI, Git integration,
  branching, pull requests, AI, offline sync, schema mutation endpoints, or
  complex path-level permissions.

## Verification

- Add service-level coverage for current-version and future-version rollback
  targets.
- Add HTTP coverage for current-version rollback target error formatting and
  partial-write prevention.
- Run foundation and replay/integrity tests plus the full test suite.
