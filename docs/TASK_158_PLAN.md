# TASK_158 Plan - Guard stale team member refresh responses

Goal: prevent delayed project member refresh responses from overwriting the
current team panel after the user changes project, returns to the project
selection screen, or clears the session.

Scope:

- Add a browser request id for manual project member refreshes.
- Capture the active project id before requesting
  `GET /projects/{project_id}/members`.
- Apply successful or failed member-list results only while the request id and
  project id still match the current browser state.
- Invalidate outstanding member refreshes when returning to the project
  selection screen or clearing session state.
- Add static UI regression coverage for the member refresh guard.

Out of scope:

- Changing backend project member APIs or RBAC behavior.
- Changing invitation delivery, membership persistence, or audit events.
- Changing canonical JSON snapshots, append-only `document_events`, schemas,
  comments, reviews, WebSocket semantics, or deployment settings.

