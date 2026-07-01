# TASK_176 Plan - Guard stale browser presence and collaboration sends

Goal: prevent delayed or mis-scoped browser collaboration sends from updating
the wrong document presence after document switches, session changes, socket
replacement, or overlapping presence heartbeats.

Scope:

- Track the document id currently owned by the browser collaboration WebSocket.
- Refuse outbound WebSocket messages when the active socket no longer matches
  the selected document.
- Add browser request id state for HTTP presence heartbeats.
- Capture document id, session token, current version, payload, and request id
  before sending HTTP presence heartbeat fallback requests.
- Ignore stale heartbeat responses and clean up the captured document presence
  with an explicit leave when a stale heartbeat completes after a document or
  session transition.
- Invalidate outstanding presence heartbeat requests when collaboration loops
  stop or selected editor state is cleared.
- Add static UI regression coverage for the stale presence and socket-send
  guards.

Out of scope:

- Changing backend presence tables, WebSocket endpoints, broadcast semantics,
  permissions, canonical document storage, append-only `document_events`,
  comments, reviews, offline sync, or deployment settings.
- Persisting browser presence request state across reloads.
- Multi-tab actor presence disambiguation beyond the existing actor/document
  row model.
