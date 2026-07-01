# TASK_171 Plan - Guard stale project invitation responses

Goal: prevent delayed browser project-invitation responses or failures from
showing an invite token, invite link, or email delivery status for the wrong
project after the user switches projects, clears the session, reloads project
state, or edits the invite form while the request is in flight.

Scope:

- Add a browser request id for project invitation creation actions.
- Track transient `creatingInvite` state so invite creation cannot overlap with
  other busy browser actions.
- Capture session user id, project id, invite email input, and invite role input
  before calling `POST /projects/{project_id}/invitations`.
- Apply successful invite responses only while the request id, session user id,
  project id, and captured invite form inputs still match.
- Ignore stale invite-create failures instead of rendering them into the active
  team action panel.
- Invalidate outstanding invite-create requests when project/session state
  changes, project bootstrap loads start, project-home loading starts, project
  opening starts, or invite form inputs change.
- Add static UI regression coverage for the invite creation request guard.

Out of scope:

- Changing invitation backend APIs, email delivery, membership policy,
  permissions, token hashing, canonical document storage, or append-only
  `document_events` semantics.
- Changing project creation, ZIP import, document create/save, rollback, replay,
  comments, reviews, WebSocket payloads, or deployment settings.
- Persisting browser invite-create request state across reloads.
