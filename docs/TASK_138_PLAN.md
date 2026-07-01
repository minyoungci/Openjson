# TASK_138_PLAN.md

## Goal

Harden stale live-text operation transforms so concurrent edits do not mutate
the wrong characters.

The current transient text collaboration layer accepts a client's
`base_text_revision` and transforms stale operations across already accepted
operations. It must avoid applying a stale delete or replace to newly inserted
text when the client intended to edit the original base text.

## Scope

- Preserve accepted inserted text when a stale delete or replace targets the
  original character at the same index.
- Reject stale operations that would require splitting one client operation
  into multiple operations to preserve another user's accepted insert or
  replacement.
- Return `VERSION_CONFLICT` for unsafe transient text transforms so clients can
  resync from `text_session.state`.
- Make the static browser client request a fresh `text_session.state` after a
  live-text `VERSION_CONFLICT`.
- Keep transient text collaboration non-canonical until `text_session.commit`
  writes through the existing content update pipeline.

## Exclusions

- Do not persist raw text operations in SQLite.
- Do not add a CRDT library or multi-operation client protocol in this task.
- Do not change durable `document_events`, snapshots, rollback, replay, or
  content save APIs.
- Do not implement automatic semantic conflict resolution for JSON arrays.

## Verification

```powershell
python -W ignore::DeprecationWarning -m unittest tests.test_realtime_collaboration tests.test_task104_collaboration_auth_sync tests.test_static_ui
python -W ignore::DeprecationWarning -m compileall app
python -W ignore::DeprecationWarning -m unittest discover -s tests
```
