# TASK_174 Plan - Guard stale bootstrap child responses

Goal: prevent delayed browser bootstrap child responses for project schemas,
team members, or usage from returning usable data after the user switches
projects, starts a newer bootstrap load, clears session state, or returns to
project selection.

Scope:

- Pass the active bootstrap request id into safe schema, member, and usage
  fetch helpers.
- Return an explicit stale result when the helper response no longer matches
  the current bootstrap request id and project id.
- Keep stale schema/member/usage data out of `state.projectSchemas`,
  `state.projectMembers`, and `state.projectUsage`.
- Preserve the existing behavior where real schema/member/usage failures are
  non-fatal to the main editor bootstrap.
- Keep manual team-member refresh behavior unchanged.
- Add static UI regression coverage for the bootstrap child-response guard.

Out of scope:

- Changing backend schema, member, usage, editor-bootstrap, invitation,
  document, WebSocket, permission, or deployment APIs.
- Changing canonical document storage, append-only `document_events`, JSON
  schema validation, ZIP import, rollback, replay, comments, reviews, or auth
  token storage.
- Persisting browser bootstrap request state across reloads.
