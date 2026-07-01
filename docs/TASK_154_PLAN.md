# TASK_154 Plan - Guard document collaboration WebSocket messages

Goal: ignore messages from stale document collaboration WebSocket instances
after document switches, reconnects, or manual loop stops.

Scope:

- Add an active-socket guard at the start of the document collaboration
  WebSocket `message` handler.
- Keep the existing document-id payload guards for collaboration state,
  comment-thread, lifecycle, live-text state, accepted operation, and commit
  handlers.
- Add static UI regression coverage that inspects the document collaboration
  socket handler directly.

Out of scope:

- Changing server WebSocket payload shape.
- Changing Redis fanout or server broadcast semantics.
- Persisting WebSocket client state.
- Changing canonical JSON snapshots, append-only `document_events`, replay,
  rollback, diff, schema validation, or text-operation transform semantics.
