# TASK_161 Plan - Guard stale document panel responses

Goal: prevent delayed validation, preview, conflict-preview, history, or diff
responses from rendering into the current document after overlapping requests,
document switches, version changes, or editor buffer changes.

Scope:

- Add browser request ids for validation, content preview, conflict preview,
  history, and diff panel loads.
- Capture selected document id and current document version for read-only
  validation/history/diff panel requests.
- Capture selected document id, base version, and editor buffer text for
  content preview and conflict preview requests.
- Apply successful responses only while the request id, selected document, and
  captured inputs still match the current browser state.
- Ignore stale errors from these panel requests instead of rendering them into
  the current document's panels.
- Invalidate outstanding document panel requests when clearing the selected
  editor, clearing session state, or detaching from a selected document after a
  live delete payload.
- Add static UI regression coverage for the document panel request guards.

Out of scope:

- Changing validation, preview, history, diff, rollback, or conflict-preview
  backend APIs.
- Persisting panel state or validation results.
- Changing canonical JSON snapshots, append-only `document_events`, schemas,
  comments, reviews, WebSocket payloads, or deployment settings.

