# TASK_049 Plan - Document Search Snapshot JSON Diagnostics

## Goal

Make project document search resilient to malformed
`json_documents.current_snapshot_json` rows without changing canonical document
read or mutation safety.

`GET /projects/{project_id}/document-search` is a read-only derived surface. If
one latest snapshot has been manually corrupted, the search endpoint should
still return searchable metadata such as `full_path` matches and clearly report
that content search for the affected document was incomplete.

## Non-Goals

- No document repair, snapshot rewrite, event replay repair, or compaction.
- No mutation semantics change.
- No DB schema change.
- No persistent search index or background indexing job.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Surface

- `GET /projects/{project_id}/document-search`

## Behavior

When a searched document has malformed `current_snapshot_json`:

- the endpoint still returns a 200 response for authorized callers
- `status` is `partial`
- `snapshot_errors` includes structured `SNAPSHOT_JSON_DECODE_FAILED`
  diagnostics
- full-path matches can still be returned because they do not require parsing
  the snapshot
- content/key/value matches for the malformed document are skipped
- a returned full-path match for the malformed document includes
  `snapshot_error`
- no document event, audit event, snapshot, or search index is written

Canonical `GET /documents/{document_id}` and document mutation APIs keep the
TASK_044 policy: malformed latest snapshots fail with the standard structured
error envelope and do not mutate state.

## Data Model

No schema change.

This task only changes read-only search response diagnostics.

## Tests

- Full-path search returns a malformed-snapshot document with `snapshot_error`.
- Content-only search returns no match for the malformed document but reports
  `snapshot_errors` and `status=partial`.
- HTTP search endpoint returns 200 with the same partial diagnostic payload.
- Search remains non-mutating when malformed snapshots are encountered.
