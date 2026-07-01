# TASK_136_PLAN.md

## Goal

Preserve a user's in-progress browser editor buffer when a live-text session
state payload arrives during join, reconnect, or retry.

TASK_135 protected the `text_session.op.accepted` path. The related
`text_session.state` path still needs the same protection because reconnecting
WebSocket clients receive the authoritative session text before they continue
typing or committing.

## Scope

- Treat `text_session.state` as the authoritative transient session shadow.
- Preserve the visible editor buffer when it has unsent or previously pending
  local live-text changes.
- Clear the stale pending-operation flag after a fresh session state arrives,
  then schedule a fresh diff from the authoritative session text to the visible
  local buffer.
- Keep clean buffers synchronized to the server session text on join or
  reconnect.

## Exclusions

- Do not persist transient text-session state.
- Do not add a CRDT/OT client library.
- Do not change `document_events`, snapshots, versioning, replay, rollback, or
  content save contracts.
- Do not change server WebSocket payload shapes.

## Verification

```powershell
python -W ignore::DeprecationWarning -m unittest tests.test_static_ui tests.test_realtime_collaboration tests.test_task104_collaboration_auth_sync
python -W ignore::DeprecationWarning -m compileall app
python -W ignore::DeprecationWarning -m unittest discover -s tests
```
