# TASK_152 Plan - Guard stale live text WebSocket payloads

Goal: keep transient live-text updates scoped to the active document and active
WebSocket connection.

Scope:

- Ignore document WebSocket `message` and `error` callbacks from sockets that
  are no longer the browser's active collaboration socket.
- Ignore `text_session.state` payloads whose `document_id` does not match the
  current selected document.
- Ignore `text_session.committed` payloads for a different selected document
  and reload the committed document id when the payload is current.
- Add static UI regression coverage for the live-text stale-payload guards.

Out of scope:

- Changing server WebSocket payload shape.
- Changing transient text-operation transform semantics.
- Persisting live-text state.
- Changing canonical JSON snapshots, append-only `document_events`, replay,
  rollback, diff, or schema validation behavior.
