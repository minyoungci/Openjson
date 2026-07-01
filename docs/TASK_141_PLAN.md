# TASK_141_PLAN.md

## Goal

Broadcast accepted HTTP document mutations to active WebSocket collaboration
clients without requiring the saving browser to send a manual `refresh` message.

Users sharing a document should see new saved checkpoints as soon as the server
accepts a normal versioned mutation. The WebSocket layer remains a notification
channel; the canonical source of truth is still `json_documents` plus
append-only `document_events`.

## Scope

- Broadcast `collaboration_state` after successful `PATCH /documents/{id}`.
- Broadcast `collaboration_state` after successful
  `PUT /documents/{id}/content`.
- Broadcast `collaboration_state` after successful
  `POST /documents/{id}/rollback`.
- Derive broadcast checkpoints from the stored `document_events` row and latest
  document state.
- Keep failed mutations, previews, and invalid JSON/schema responses from
  broadcasting.

## Exclusions

- Do not make WebSocket state canonical.
- Do not change document event schemas or SQLite tables.
- Do not implement CRDT, automatic merge, branching, review, Git, or AI
  behavior.
- Do not add delete tombstone broadcasts in this task.

## Verification

```powershell
python -W ignore::DeprecationWarning -m unittest tests.test_realtime_collaboration tests.test_collaboration_monitoring tests.test_static_ui
python -W ignore::DeprecationWarning -m compileall app
python -W ignore::DeprecationWarning -m unittest discover -s tests
```
