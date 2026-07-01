# TASK_163 Plan - Guard stale rollback responses

Goal: prevent delayed browser rollback responses from updating the current
editor after the user switches documents, a newer rollback starts, or the
selected document version changes while the rollback request is in flight.

Scope:

- Add a browser request id for rollback requests.
- Track a transient `rollingBack` state so rollback cannot overlap with other
  editor mutations in the static UI.
- Capture selected document id, current base version, and target version before
  calling `POST /documents/{document_id}/rollback`.
- Apply successful rollback responses only while the request id, selected
  document, captured base version, and target version still match the current
  browser state.
- Ignore stale rollback errors instead of rendering them into the current
  document's rollback panel.
- Reload the captured document id after a current rollback succeeds.
- Invalidate outstanding rollback requests when clearing the selected editor,
  clearing session state, detaching from a live-deleted selected document, or
  switching to another selected document.
- Add static UI regression coverage for the rollback request guard.

Out of scope:

- Changing the rollback backend API, rollback event model, or replay semantics.
- Changing append-only `document_events`, version conflict semantics, schema
  validation, review workflow, or WebSocket payloads.
- Persisting browser rollback request state across reloads.
