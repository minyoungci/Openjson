# TASK_150 Plan - Guard stale WebSocket presence leave

Goal: prevent an older WebSocket disconnect from deleting a newer presence
heartbeat for the same actor and document.

Scope:

- Track the last `editor_presence.last_seen_at` value written by each document
  WebSocket connection.
- On WebSocket disconnect, delete presence only when the current row still
  matches the timestamp written by that connection.
- Keep explicit HTTP `DELETE /documents/{document_id}/presence` behavior
  unchanged; browser navigation and document switch leave requests still remove
  the actor presence immediately.
- Add regression coverage for guarded service-level leave and WebSocket close
  without socket-owned presence.

Out of scope:

- Persisting presence connection ids or presence history.
- Changing `editor_presence` schema.
- Changing canonical document snapshots, append-only `document_events`, diff,
  rollback, or replay behavior.
- Multi-tab actor presence disambiguation beyond the existing
  `(document_id, actor_id)` row.
