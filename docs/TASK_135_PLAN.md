# TASK_135_PLAN.md

## Goal

Preserve a user's in-progress browser editor buffer when remote live-text
operations are accepted by the server.

TASK_134 made accepted text-session payloads authoritative by including
`content_text`. That keeps each client shadow aligned with the server session,
but a remote accepted payload can still arrive while the local user has unsent
or unacknowledged text in the editor buffer. In that case the browser must not
overwrite the visible local buffer.

## Scope

- Detect whether the local editor buffer has unsent or pending live-text
  changes before applying a remote accepted operation.
- Always realign `liveTextShadow` to the authoritative server text when it is
  present.
- If the local buffer is clean, reflect the remote operation into the visible
  editor buffer.
- If the local buffer is dirty or a local operation is pending, preserve the
  visible local buffer and schedule a fresh diff after the pending operation is
  acknowledged.
- Keep commit blocked until pending local live-text operations are acknowledged.

## Exclusions

- Do not persist transient text-session state.
- Do not add a CRDT/OT client library.
- Do not change `document_events`, latest snapshots, rollback, replay, or
  content save API contracts.
- Do not implement offline conflict resolution beyond the existing queued
  content-save APIs.

## Verification

```powershell
python -W ignore::DeprecationWarning -m unittest tests.test_static_ui tests.test_realtime_collaboration tests.test_task104_collaboration_auth_sync
python -W ignore::DeprecationWarning -m compileall app
python -W ignore::DeprecationWarning -m unittest discover -s tests
```
