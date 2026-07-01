# TASK_131_PLAN.md

## Goal

Harden the WebSocket collaborative text-session permission boundary.

The browser can open a collaborative text session to view the current document
text, but only users with document write permission may change transient
collaborative text or commit it into canonical document history.

## Scope

- Keep `text_session.join` available to users with document read permission.
- Require `document:write` before accepting `text_session.op` messages.
- Require `document:write` before accepting `text_session.commit` messages.
- Preserve the existing canonical persistence rule: text session commits write
  through the normal content update pipeline and append-only `document_events`.
- Add a WebSocket regression test proving a viewer cannot mutate the shared
  transient session text.

## Exclusions

- Do not add a new collaboration storage table.
- Do not change the document event model, replay, rollback, or schema
  validation pipeline.
- Do not implement CRDT persistence or offline-first replicated storage.
- Do not change project RBAC roles.

## Verification

```powershell
python -m unittest tests.test_realtime_collaboration
python -m unittest tests.test_task104_collaboration_auth_sync
python -m unittest discover -s tests
```
