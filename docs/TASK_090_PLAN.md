# TASK_090_PLAN.md

## Objective

Allow raw JSON editor clients to submit JSON text through the existing content
preview/save endpoints while keeping canonical persistence strictly structured,
validated, and event-backed.

## Scope

- Extend `POST /documents/{document_id}/content-preview`.
- Extend `PUT /documents/{document_id}/content`.
- Accept exactly one of:
  - `content`: already parsed JSON value
  - `content_text`: raw JSON text from an editor
- Parse `content_text` server-side and return line/column diagnostics for
  malformed JSON.

## Policy

- Invalid JSON text must never become `json_documents.current_snapshot_json`.
- Invalid JSON text must not create `document_events`, increment versions, or
  write audit rows.
- Parsed text must still produce canonical object/array content.
- Valid parsed text still flows through generated JSON Patch, schema
  validation, append-only event insert, and snapshot update in one transaction.
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, automatic
  merge/conflict resolution, or complex path-level permissions.

## Verification

- Valid `content_text` preview returns generated patch without mutation.
- Valid `content_text` save creates an ordinary update event and replay still
  matches the latest snapshot.
- Malformed `content_text`, missing content source, and ambiguous content
  source fail without partial writes.
- Existing parsed `content` requests remain supported.
