# TASK_169 Plan - Guard stale JSON file import results

Goal: prevent delayed browser JSON file reads from overwriting the wrong create
form or editor buffer after the user switches projects, switches documents,
reloads a document, closes the create panel, or edits the target form/buffer
while the file read is in flight.

Scope:

- Add browser request ids for create-form JSON file imports and editor-buffer
  JSON file imports.
- Capture project id, selected document id, create panel visibility, form path,
  form content, schema selection, selected file, editor document id, editor
  version, and editor buffer text before reading a local JSON file.
- Apply file import results only while the captured context still matches the
  visible target.
- Ignore stale file-read and JSON-parse failures instead of rendering them into
  the active validation panel after navigation or buffer changes.
- Invalidate pending file imports when project/session state changes, bootstrap
  reloads start, selected document changes, the create panel closes, create form
  inputs change, or editor text changes.
- Add static UI regression coverage for the file import guards.

Out of scope:

- Changing document create/save backend APIs, schema validation, permissions, or
  append-only `document_events` semantics.
- Changing ZIP import, rollback, replay, WebSocket payloads, comments, reviews,
  or deployment settings.
- Persisting browser file import state across reloads.
