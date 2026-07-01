# TASK_162 Plan - Guard stale content save responses

Goal: prevent delayed manual save or autosave responses from updating the
current browser editor state after the user switches documents, the base version
changes, or the editor buffer changes while the save is in flight.

Scope:

- Add a browser request id for content save requests.
- Track a general `saving` state so manual save and autosave share one
  in-flight guard.
- Capture selected document id, base version, editor text, and merge strategy
  before calling `PUT /documents/{document_id}/content`.
- Apply successful save responses only while the request id, selected document,
  base version, and editor text still match the current browser state.
- Use the captured save payload for offline queue fallback instead of reading
  mutable current editor state after a failure.
- Ignore stale save errors instead of rendering them into the current document's
  conflict or validation panels.
- Invalidate outstanding save requests when clearing the selected editor,
  clearing session state, detaching from a live-deleted selected document, or
  switching to another selected document.
- Add static UI regression coverage for the save request guard.

Out of scope:

- Changing the content save, content preview, conflict preview, or offline sync
  backend APIs.
- Changing append-only `document_events`, version conflict semantics, schema
  validation, review workflow, or WebSocket payloads.
- Persisting browser save request state across reloads.

