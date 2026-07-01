# TASK_159 Plan - Guard stale project home loads

Goal: prevent delayed project-home list responses from replacing the current
workspace/editor screen after the user opens a project, starts project creation,
logs out, or otherwise invalidates the project selection view.

Scope:

- Add a browser request id for project-home list loads.
- Keep workspace/project list data and per-workspace errors local until the
  response is confirmed as the latest project-home request.
- Ignore stale project-home success and failure responses.
- Avoid letting stale `finally` blocks clear the active loading state for a
  newer project load.
- Invalidate outstanding project-home loads when opening a project, starting
  project creation, or clearing session state.
- Add static UI regression coverage for the project-home load guard.

Out of scope:

- Changing workspace/project backend APIs.
- Changing project membership, invitation, or RBAC behavior.
- Changing canonical JSON snapshots, append-only `document_events`, schemas,
  comments, reviews, WebSocket semantics, or deployment settings.

