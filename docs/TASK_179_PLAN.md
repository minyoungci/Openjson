# TASK_179 Plan - Guard stale conflict keep-local-buffer actions

Goal: prevent the browser conflict recovery action from writing an old local
buffer into the editor after the user switches documents, clears session state,
starts another keep-local action, or edits the buffer while the latest
document reload is still in flight.

Scope:

- Add browser request id state for the keep-local-buffer action.
- Capture document id and conflict-local text before reloading the latest
  document snapshot.
- Apply the preserved local buffer only while the request id, selected
  document id, and conflict-local text still match.
- Invalidate in-flight keep-local actions when the editor buffer changes,
  selected document changes, editor state clears, or session state clears.
- Add static UI regression coverage for the keep-local-buffer guard.

Out of scope:

- Changing conflict-preview APIs, save APIs, auto-merge policy, canonical
  snapshots, append-only `document_events`, offline sync, or WebSocket
  collaboration behavior.
- Persisting conflict recovery state across browser reloads.
