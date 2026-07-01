# TASK_156 Plan - Invalidate bootstrap loads when returning to project home

Goal: prevent delayed project editor-bootstrap responses from re-opening the
workspace editor after the user has intentionally returned to the project
selection screen.

Scope:

- Add a browser helper that invalidates outstanding bootstrap requests.
- Reuse the helper for session clearing.
- Call the helper when entering the project home screen before loading
  workspaces and projects.
- Keep existing collaboration and project WebSocket shutdown behavior.
- Add static UI regression coverage that verifies project-home navigation
  invalidates stale bootstrap responses.

Out of scope:

- Changing backend API response shape.
- Changing persisted project, document, event, schema, comment, or review data.
- Changing WebSocket server semantics.
- Adding browser routing framework state.

