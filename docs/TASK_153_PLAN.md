# TASK_153 Plan - Fix project workspace WebSocket message guard

Goal: ensure project document-list WebSocket updates are accepted only from the
active project workspace socket.

Scope:

- Fix the project workspace WebSocket `message` handler to compare against
  `state.projectSocket`, not the document collaboration socket.
- Keep the existing `project_id` payload guard in `applyProjectDocumentsChanged`
  so stale project messages cannot refresh the wrong project after navigation.
- Add static UI regression coverage that inspects the project workspace socket
  handler directly.

Out of scope:

- Changing server WebSocket payload shape.
- Persisting project workspace WebSocket state.
- Adding a project event store.
- Changing canonical JSON snapshots, append-only `document_events`, replay,
  rollback, diff, schema validation, or text-operation semantics.
