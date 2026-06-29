# Comments Baseline

This document records the approved TASK_004 minimal comments/memo policy.

TASK_004 adds collaboration metadata only. It does not add review workflow,
realtime comment updates, mentions, notifications, UI, AI summarization, Git
integration, branching, pull requests, WebSocket, offline sync, or complex
path-level permissions.

## Model

`comment_threads` anchor comments to:

- whole document
- JSON Pointer path
- document event

`comments` stores append-only messages within a thread.

Thread status:

- `open`
- `resolved`

Reopen sets status back to `open`.

## API

- `POST /documents/{document_id}/comment-threads`
- `GET /documents/{document_id}/comment-threads`
- `POST /comment-threads/{thread_id}/comments`
- `POST /comment-threads/{thread_id}/resolve`
- `POST /comment-threads/{thread_id}/reopen`

All endpoints require `X-Actor-Id` and project membership.

## RBAC Policy

- `owner`, `admin`, `editor`, `reviewer`: read and write comments.
- `viewer`: read comments only.
- non-members: no access.

This remains project-level RBAC only. Path-level permissions are intentionally
not implemented.

## Anchor Policy

- document comments cannot include path or event anchors
- path comments require a syntactically valid JSON Pointer path
- event comments require an event belonging to the same document

Path comments do not require the path to exist in the latest snapshot.

## Soft Delete Policy

Existing comment threads remain listable after document soft delete. Creating a
new comment thread on a soft-deleted document is rejected.

## Integrity Policy

Comment operations are metadata-only.

They must not:

- change document snapshots
- increment document versions
- create document events
- delete or rewrite comments
- delete or rewrite document history

The core replay invariant remains:

```text
Replay(DocumentEvent[0..N]) == json_documents.current_snapshot_json
```
