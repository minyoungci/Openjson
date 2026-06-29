# TASK_091_PLAN.md

## Objective

Return editor-ready JSON text in the read-only editor-state response so a raw
JSON editor can load a document without deriving text formatting client-side.

## Scope

- Extend `GET /documents/{document_id}/editor-state`.
- Add `document.content_text` as deterministic pretty JSON generated from the
  latest canonical snapshot.
- Add `document.content_text_format` metadata.

## Policy

- `content_text` is a read-only projection of
  `json_documents.current_snapshot_json`.
- It is not a second source of truth and is not persisted separately.
- Editor-state remains read-only: no document events, snapshot updates,
  version increments, audit rows, or validation persistence.
- Raw editor saves must still use `PUT /documents/{document_id}/content` with
  `content_text` or structured `content`, which generates auditable JSON Patch
  events.
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, automatic
  merge/conflict resolution, or complex path-level permissions.

## Verification

- Editor-state returns parseable `content_text` that equals `document.content`
  when parsed.
- `content_text` is deterministic and pretty formatted.
- Editor-state remains read-only and replay consistency still holds.
- HTTP route and API token scope continue to work.
