# TASK_157 Plan - Guard stale schema match preview responses

Goal: prevent delayed create-document schema match preview responses from
overwriting the current create panel after the user changes project, path, or
explicit schema selection.

Scope:

- Add a browser request id for create-time schema match preview.
- Capture the active project id and candidate full path before requesting
  `GET /projects/{project_id}/schema-matches`.
- Apply successful or failed preview results only while the request id, project
  id, candidate full path, create panel visibility, and automatic-schema mode
  still match the current browser state.
- Add static UI regression coverage for the schema match preview guard.

Out of scope:

- Changing backend schema match API behavior.
- Changing schema binding priority or validation rules.
- Persisting browser preview state.
- Changing canonical JSON snapshots, append-only `document_events`, schemas,
  comments, reviews, WebSocket semantics, or deployment settings.

