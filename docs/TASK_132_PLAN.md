# TASK_132_PLAN.md

## Goal

Make WebSocket collaborative text operations idempotent for normal retry and
duplicate-delivery cases.

Realtime transports can deliver the same client edit more than once when a
browser reconnects, retries, or loses an acknowledgement. A duplicate
`text_session.op` must not mutate the transient shared text twice, because that
could later be committed into canonical `document_events`.

## Scope

- Accept optional `client_operation_id` on `text_session.op` messages.
- Treat `(actor_id, client_operation_id)` as an idempotency key within the
  active transient text session.
- Return the original accepted operation with `idempotent_replay = true` when a
  duplicate id is received.
- Do not broadcast duplicate replays to other sockets.
- Send `client_operation_id` from the static browser app for live text edits.
- Avoid double-applying the local user's accepted operation in the browser
  shadow text.

## Exclusions

- Do not persist text operation ids in SQLite.
- Do not make raw text canonical storage.
- Do not change the append-only `document_events` schema.
- Do not implement a full CRDT library or offline-first replicated log.

## Verification

```powershell
python -m unittest tests.test_realtime_collaboration tests.test_static_ui
python -m unittest tests.test_task104_collaboration_auth_sync
python -m unittest discover -s tests
```
