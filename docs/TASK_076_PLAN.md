# TASK_076_PLAN.md

## Objective

Harden and document delete/restore event metadata for lifecycle-only document
mutations.

## Policy

- Delete and restore are append-only `document_events`.
- They change the document lifecycle marker, not the JSON snapshot content.
- Their stored `patch`, `inverse_patch`, and `changed_paths` arrays are empty.
- Their `before_values` and `after_values` store the root snapshot record:
  `{"path": "", "exists": true, "value": <current snapshot>}`.
- Replay consistency must remain true after create -> delete -> restore.
- This task does not add realtime collaboration, UI, Git integration,
  branching, pull requests, AI, offline sync, schema mutation endpoints, or
  complex path-level permissions.

## Verification

- Add a restore test that inspects history for delete and restore event
  metadata.
- Run restore/foundation/event-chain tests and the full test suite.
