# TASK_139_PLAN.md

## Goal

Reject out-of-bounds live-text operations instead of silently clamping them to
the current session text.

Collaborative text operations carry client-provided indexes. If an index or
range is invalid after stale-operation transform, applying it at a clamped
position can mutate different text than the user intended. Invalid bounds
should fail before the transient session revision advances.

## Scope

- Validate transformed `insert`, `delete`, and `replace` bounds against the
  current transient session text.
- Allow insert at the end of the current text.
- Reject insert indexes greater than the current text length.
- Reject delete/replace ranges that exceed the current text length.
- Leave session text, revision, and accepted operation history unchanged on
  invalid bounds.

## Exclusions

- Do not persist transient text operations.
- Do not change durable document event schemas.
- Do not change JSON Patch or content save APIs.
- Do not introduce a CRDT library or multi-operation transform protocol.

## Verification

```powershell
python -W ignore::DeprecationWarning -m unittest tests.test_realtime_collaboration tests.test_task104_collaboration_auth_sync tests.test_static_ui
python -W ignore::DeprecationWarning -m compileall app
python -W ignore::DeprecationWarning -m unittest discover -s tests
```
