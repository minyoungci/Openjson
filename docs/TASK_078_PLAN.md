# TASK_078_PLAN.md

## Objective

Harden update patch handling so accepted update events always represent a real
JSON snapshot change.

## Policy

- `PATCH /documents/{document_id}` must produce a candidate snapshot different
  from the current snapshot.
- Semantic no-op patches return `PATCH_APPLY_FAILED`.
- Examples of semantic no-op patches:
  - replacing a scalar with the same value
  - adding an existing object key with the same value
  - replacing the root with an identical object or array
  - multi-operation patches that change a value and then restore the original
    final snapshot
- Rejected no-op patches must not insert a `document_events` row.
- Rejected no-op patches must not update `json_documents.current_version` or
  `json_documents.current_snapshot_json`.
- Delete, restore, and rollback keep their existing lifecycle/rollback event
  semantics.
- This task does not add realtime collaboration, UI, Git integration,
  branching, pull requests, AI, offline sync, schema mutation endpoints, or
  complex path-level permissions.

## Verification

- Add service-level coverage for same-value, root, and canceling
  multi-operation no-op update patches.
- Add HTTP coverage for same-value no-op update patch error formatting and
  partial-write prevention.
- Run foundation and replay/integrity tests plus the full test suite.
