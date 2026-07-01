# TASK_151 Plan - Ignore stale collaboration state payloads

Goal: keep the browser collaboration panel tied to the currently selected
document when asynchronous polling or WebSocket messages arrive late.

Scope:

- Ignore `collaboration_state` payloads whose `document_id` does not match the
  browser's current `selectedDocumentId`.
- Preserve existing document lifecycle, project document-list, and comment
  notification guards.
- Add static UI regression coverage for the selected-document guard.

Out of scope:

- Changing WebSocket payload shape.
- Persisting client UI state.
- Changing canonical JSON snapshots, append-only `document_events`, diff,
  rollback, replay, or schema validation behavior.
- Multi-tab presence identity changes.
