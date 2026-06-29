# TASK_101_PLAN.md

## Objective

Add realtime-style edit monitoring for users working on the same JSON document.

This task exposes who is currently viewing or editing a document, whether their
local buffer is dirty, which base version they are editing from, and which
accepted save/autosave checkpoints have been created since another user's
loaded version.

## Scope

- Add document-scoped editor presence.
- Add document-scoped collaboration state read API.
- Show active users in the local editor shell.
- Show recent accepted checkpoints from `document_events`.
- Add optional autosave in the local editor shell.
- Keep all accepted saves flowing through the existing content update API.

## API

### Presence Heartbeat

```text
POST /documents/{document_id}/presence
```

Request:

```json
{
  "status": "editing",
  "base_version": 3,
  "dirty": true,
  "cursor_path": "/model/name"
}
```

`status` may be `viewing` or `editing`.

### Leave Presence

```text
DELETE /documents/{document_id}/presence
```

Removes the actor's current presence row for the document.

### Collaboration State

```text
GET /documents/{document_id}/collaboration-state?since_version=3
```

Returns:

- document identity and current version
- active users with role-like editing state
- stale-base flags
- recent accepted checkpoints from `document_events`
- whether the document has updates newer than `since_version`

## Data Model

Add `editor_presence`.

This table is transient operational state, not the canonical document source of
truth. It is allowed to update in place because it does not represent JSON
content history.

Accepted document content changes remain stored only through append-only
`document_events`.

## Autosave Policy

Autosave is a client-side convenience. When enabled, the local editor waits for
a short idle window and then calls the existing canonical content save API:

```text
PUT /documents/{document_id}/content
```

Autosave still requires:

- valid JSON syntax
- current `base_version`
- existing project write permission
- schema validation success when bound

Autosave failures do not create events.

## Excluded

- CRDT/Yjs
- Operational transform
- WebSocket text streaming
- Path-level merge/conflict auto-resolution
- Offline sync
- Branching
- Pull request workflow
- Git integration
- AI inference
