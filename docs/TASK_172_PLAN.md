# TASK_172 Plan - Guard stale project invitation acceptance responses

Goal: prevent delayed browser invitation-acceptance responses or failures from
opening the wrong project, clearing the wrong invite token, or rendering stale
join status after the user changes sessions, edits the invite token, switches
projects, or starts a fresh project load while `POST /invitations/accept` is in
flight.

Scope:

- Add a browser request id for project invitation acceptance actions.
- Track transient `acceptingInvite` state so invitation acceptance cannot
  overlap with other busy browser actions.
- Capture session user id and invite token input before calling
  `POST /invitations/accept`.
- Apply successful manual invite acceptance only while the request id, session
  user id, and captured token input still match.
- Apply successful pending invite-link acceptance only while the request id,
  session user id, pending token, and token input still match.
- Ignore stale invite-accept failures instead of rendering them into the
  project setup panel.
- Invalidate outstanding invite-accept requests when project/session state
  changes, project bootstrap loads start, project-home loading starts, project
  opening starts, or the invite token input changes.
- Add static UI regression coverage for the invite acceptance request guard.

Out of scope:

- Changing invitation backend APIs, token hashing, token expiry, email
  delivery, membership rules, permissions, authentication storage, canonical
  document storage, or append-only `document_events` semantics.
- Changing project creation, invite creation, ZIP import, document create/save,
  rollback, replay, comments, reviews, WebSocket payloads, or deployment
  settings.
- Persisting browser invite-accept request state across reloads.
