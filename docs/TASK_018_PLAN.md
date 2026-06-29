# TASK_018 Plan - Project Document Search

## Goal

Add a read-only project-scoped search API over latest JSON document snapshots.

This gives callers a basic way to find documents by path, JSON object key, and
scalar JSON value without introducing a search index or frontend work.

## Non-Goals

- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permissions.
- No dedicated search engine or persistent search index.
- No mutation endpoint and no document event writes.

## API

`GET /projects/{project_id}/document-search`

Query parameters:

- `q`: required non-empty search text, case-insensitive.
- `path`: optional JSON Pointer. When supplied, JSON content search is limited
  to that subtree. Full path matches are only evaluated when `path` is absent.
- `include_deleted`: optional boolean, default `false`.
- `limit`: optional matching-document page size, 1 through 100, default 50.
- `offset`: optional matching-document offset, default 0.
- `max_matches_per_document`: optional cap for returned matches per document,
  1 through 20, default 5.

The endpoint requires project `document:read` permission. Project-scoped API
tokens may call it only for their own project.

## Matching Policy

- `full_path`: case-insensitive substring match against `json_documents.full_path`.
- `key`: case-insensitive substring match against object keys.
- `value`: case-insensitive substring match against scalar JSON values.
- JSON Pointer escaping is preserved in returned paths.
- Object and array values are traversed, but only object keys and scalar values
  are matched directly.

## Malformed Snapshot Policy

If a searched document's `current_snapshot_json` is malformed, the endpoint
returns `status=partial` with `snapshot_errors`. Full-path matches can still be
returned because they do not require parsing the snapshot, but content/key/value
matches for the malformed document are skipped.

See `docs/TASK_049_PLAN.md`.

## Response Shape

```json
{
  "project_id": "project_dev",
  "documents": [
    {
      "id": "doc_001",
      "project_id": "project_dev",
      "full_path": "config/model.json",
      "current_version": 2,
      "schema_id": null,
      "deleted_at": null,
      "match_count": 1,
      "matches_truncated": false,
      "matches": [
        {
          "match_type": "value",
          "path": "/optimizer/name",
          "key": null,
          "value": "adam"
        }
      ]
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 1,
    "has_more": false
  },
  "filters": {
    "q": "adam",
    "path": null,
    "include_deleted": false,
    "max_matches_per_document": 5
  }
}
```

## Data Model

No schema change.

The API reads `json_documents.current_snapshot_json` for documents in the
project and returns derived search matches. It does not write audit rows,
document events, snapshots, or search index rows.

## Tests

- Full path, JSON key, scalar value, nested object, array item, and escaped
  JSON Pointer matches.
- Optional path restriction including root path and missing subtree policy.
- Soft-deleted documents are hidden by default and visible with
  `include_deleted=true`.
- Pagination and per-document match truncation.
- Invalid query, invalid path, and invalid pagination are rejected.
- Viewer can search; non-member is denied.
- HTTP route and project API token scope are verified.
- Malformed latest snapshots produce partial diagnostics without mutating
  documents or events.
