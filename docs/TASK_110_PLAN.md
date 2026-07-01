# TASK_110 Plan: Document Notes UI

## Goal

Expose the existing document comment thread APIs in the local static editor so
users can add and review document notes from the workspace screen.

## Scope

- Add a compact Notes panel to the inspector.
- Support document, JSON Pointer path, and document-event anchors through the
  existing comment-thread API.
- Support listing threads, adding replies, resolving threads, and reopening
  threads through existing endpoints.
- Keep comments separate from canonical JSON content and `document_events`.
- Add static UI tests for the new controls and client API calls.

## Out of Scope

- New database tables or schema changes.
- Realtime comment delivery, notifications, mentions, or email alerts.
- Review workflow changes.
- Git integration, branching, pull requests, AI features, or path-level
  permission rules.
- Changing document mutation, rollback, diff, autosave, or WebSocket
  checkpoint behavior.

## Data Model

No data-model change. The UI uses existing `comment_threads` and `comments`
rows. `comments` remains append-only, while thread status updates continue to
use the existing resolve/reopen endpoints.

## API

No API change. The UI uses:

- `GET /documents/{document_id}/comment-threads`
- `POST /documents/{document_id}/comment-threads`
- `POST /comment-threads/{thread_id}/comments`
- `POST /comment-threads/{thread_id}/resolve`
- `POST /comment-threads/{thread_id}/reopen`

## Test Plan

- Verify the static HTML exposes the Notes controls.
- Verify the client JavaScript calls the comment-thread endpoints.
- Run the existing comment service tests to confirm comment operations still do
  not mutate JSON snapshots or document events.
