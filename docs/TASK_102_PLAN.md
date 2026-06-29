# TASK_102_PLAN.md

## Objective

Add the first usable multi-user editing experience on top of the existing
versioned JSON document foundation.

This task introduces local team onboarding controls in the static editor and a
WebSocket collaboration channel for document presence and checkpoint updates.
Accepted JSON mutations still use the existing HTTP content/patch APIs and
still create append-only `document_events`.

## Included

- Local UI controls for creating a user and adding that user to the current
  project.
- Local UI member list with a quick "Use" action for testing as another actor.
- WebSocket document collaboration endpoint:
  - `WS /ws/documents/{document_id}/collaboration?actor_id={actor_id}`
- WebSocket messages for:
  - initial collaboration state
  - presence heartbeat
  - refresh/checkpoint broadcast
  - ping/pong
  - structured error payloads
- UI WebSocket connection with HTTP polling fallback.
- Tests for WebSocket state delivery, presence broadcast, permission failure,
  and static UI wiring.

## Explicitly Excluded

- Password login, invitation emails, refresh tokens, SSO, or production auth.
- CRDT, operational transform, text-stream merging, and automatic merge.
- Offline sync.
- Branching, pull requests, Git integration, or AI features.
- Complex path-level permissions.
- Review workflow changes.

## Design Notes

The WebSocket layer is an operational notification channel, not a new source of
truth. Presence rows remain transient. Checkpoints are derived from accepted
`document_events`.

The client may use WebSocket to learn that another user saved a new version, but
the save itself must still go through `PUT /documents/{document_id}/content` or
the patch endpoint with `base_version`. Stale saves remain rejected with
`VERSION_CONFLICT`.

The WebSocket connection manager is in memory for this local MVP. It is not
multi-process or multi-node safe; Redis or a similar pub/sub layer is a later
production concern.
