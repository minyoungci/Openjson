# TASK_149 Plan - HTTP presence WebSocket broadcast

Goal: make browser polling fallback presence updates visible to other active
document WebSocket clients immediately.

Scope:

- Broadcast `collaboration_state` after successful
  `POST /documents/{document_id}/presence`.
- Broadcast `collaboration_state` after successful
  `DELETE /documents/{document_id}/presence`.
- Keep WebSocket-originated `presence` messages and disconnect leave handling
  unchanged.
- Add regression coverage for HTTP heartbeat and leave broadcasts reaching a
  subscribed document WebSocket client.

Out of scope:

- Persisting presence history.
- Changing `editor_presence` schema.
- Changing document snapshots, append-only `document_events`, rollback, diff,
  or replay behavior.
- Adding multi-document editing from one browser tab.
