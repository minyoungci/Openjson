# TASK_004 Plan: Path-Level Comments / Memo

TASK_004 adds minimal comment/memo metadata anchored to a document, JSON Pointer
path, or document event.

Do not implement review workflow, realtime comment updates, mentions,
notifications, UI, AI summarization, Git integration, branching, pull requests,
WebSocket, offline sync, or complex path-level permissions in TASK_004.

## Scope

- Add `comment_threads` table.
- Add `comments` table.
- Support document-level comments.
- Support JSON Pointer path-level comments.
- Support event-level comments.
- Support adding comments to an existing thread.
- Support resolving and reopening comment threads.
- Enforce project-level RBAC from `docs/RBAC_BASELINE.md`.

## DB Changes

Add `comment_threads`:

- `id`
- `project_id`
- `document_id`
- `anchor_type`: `document`, `path`, or `event`
- `anchor_path` nullable
- `anchor_event_id` nullable
- `status`: `open` or `resolved`
- `created_by`
- `created_at`
- `updated_at`
- `resolved_by` nullable
- `resolved_at` nullable

Add `comments`:

- `id`
- `thread_id`
- `author_id`
- `body`
- `created_at`

`comments` rows are append-only at the DB level with update/delete rejection
triggers. Thread status changes are allowed for resolve/reopen.

## Anchor Policy

- `document`: no path or event id.
- `path`: requires a syntactically valid JSON Pointer path.
- `event`: requires a `document_events.id` belonging to the same document.

TASK_004 validates JSON Pointer syntax but does not require the path to exist in
the current snapshot. This keeps comments stable across later document edits.

## Soft Delete Policy

- Existing comment threads remain listable after document soft delete.
- Creating a new comment thread on a soft-deleted document is rejected with
  `DOCUMENT_NOT_FOUND`.
- Existing thread resolve/reopen remains metadata-only and project-permission
  controlled.

## API Endpoints

- `POST /documents/{document_id}/comment-threads`
- `GET /documents/{document_id}/comment-threads`
- `POST /comment-threads/{thread_id}/comments`
- `POST /comment-threads/{thread_id}/resolve`
- `POST /comment-threads/{thread_id}/reopen`

All endpoints require `X-Actor-Id`.

## Data Integrity Policy

Comment operations must not:

- update `json_documents.current_snapshot_json`
- increment `json_documents.current_version`
- create `document_events`
- modify existing `comments` rows
- delete comment history

## Test Plan

- create document-level, path-level, and event-level comment threads
- reject invalid JSON Pointer path anchors
- reject event anchors not belonging to the document
- add comment to existing thread
- resolve and reopen thread
- viewer can list but cannot write comments
- non-member is denied
- comments remain listable after document soft delete
- new comment thread on soft-deleted document is rejected
- comments table rejects direct SQL update/delete
- comment route registration
- existing replay consistency tests continue to pass
