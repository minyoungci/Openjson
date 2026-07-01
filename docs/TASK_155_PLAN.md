# TASK_155 Plan - Guard stale browser bootstrap responses

Goal: prevent delayed project editor-bootstrap responses from older browser
requests from overwriting the active project or document view after a project
switch, logout, document switch, or realtime refresh race.

Scope:

- Add a monotonically increasing browser bootstrap request id.
- Capture the target project id at the start of `loadBootstrap`.
- Fetch project bootstrap, schemas, members, and usage using that captured
  project id.
- Apply the response only if the request id and project id still match the
  active browser state.
- Clear loading state for stale requests only when no newer bootstrap request
  has superseded them.
- Add static UI regression coverage for the stale bootstrap guard.

Out of scope:

- Changing backend API response shape.
- Changing WebSocket payload semantics.
- Persisting browser request state.
- Changing canonical JSON snapshots, append-only `document_events`, replay,
  rollback, diff, schema validation, comments, or review workflow behavior.

