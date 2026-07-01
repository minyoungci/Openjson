# TASK_160 Plan - Guard stale comment thread loads

Goal: prevent delayed note/comment thread list responses or completed comment
actions from replacing the current document's notes after overlapping refreshes
or document switches.

Scope:

- Add a browser request id for comment thread list loads.
- Apply `GET /documents/{document_id}/comment-threads` results only while the
  response belongs to the latest comment-thread request for the selected
  document.
- Ignore stale comment-thread load errors instead of rendering them into the
  current document's notes panel.
- Invalidate outstanding comment-thread loads when clearing the selected editor,
  deleting the selected document from a live lifecycle payload, or clearing
  session state.
- Capture the selected document id before create/reply/resolve/reopen comment
  actions and avoid updating the current UI if the user switches documents while
  the action is in flight.
- Add static UI regression coverage for the comment-thread load and action
  guards.

Out of scope:

- Changing comment thread backend APIs, persistence, or WebSocket payloads.
- Changing comment permissions, review workflow, or notification delivery.
- Changing canonical JSON snapshots, append-only `document_events`, schemas,
  project membership, or deployment settings.

