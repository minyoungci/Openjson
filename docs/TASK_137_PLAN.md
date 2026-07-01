# TASK_137_PLAN.md

## Goal

Preserve an unacknowledged local live-text edit when the WebSocket disconnects
or errors before the browser receives `text_session.op.accepted`.

The browser optimistically advances `liveTextShadow` to the editor buffer after
sending a local operation. If the socket closes before acknowledgement, the
shadow can equal the visible buffer even though the server may not have applied
the operation. A later `text_session.state` payload must not treat that buffer
as clean and overwrite it.

## Scope

- Track whether a local live-text operation became unacknowledged because of a
  WebSocket error, close, or server error payload.
- Include that flag in the local-buffer preservation checks for
  `text_session.state` and remote accepted operations.
- Clear the flag after an acknowledgement or after a fresh session state has
  been used to re-diff the visible buffer.
- Keep all state browser-local and transient.

## Exclusions

- Do not persist transient text-session operations.
- Do not change WebSocket payload schemas.
- Do not add a CRDT/OT client library.
- Do not change canonical snapshots, append-only `document_events`, rollback,
  replay, or content save APIs.

## Verification

```powershell
python -W ignore::DeprecationWarning -m unittest tests.test_static_ui tests.test_realtime_collaboration tests.test_task104_collaboration_auth_sync
python -W ignore::DeprecationWarning -m compileall app
python -W ignore::DeprecationWarning -m unittest discover -s tests
```
