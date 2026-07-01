# TASK_170 Plan - Guard stale project creation responses

Goal: prevent delayed browser project-creation responses or failures from
clearing the current project form, rendering into the wrong project-selection
screen, or opening a newly created project after the user navigates away,
changes sessions, closes the create panel, or edits the create form while the
request is in flight.

Scope:

- Add a browser request id for project creation actions.
- Track transient `creatingProject` state so project creation cannot overlap
  with other busy browser actions.
- Capture actor id, workspace name input, project name input, and project
  description input before calling `POST /workspaces` and
  `POST /workspaces/{workspace_id}/projects`.
- Apply successful project-create responses only while the request id, actor id,
  visible create panel, and captured form inputs still match.
- Ignore stale project-create failures instead of rendering them into the
  current project setup output.
- Invalidate outstanding project-create requests when project/session state
  changes, project-home loading starts, project opening starts, the create panel
  is closed, or project-create form inputs change.
- Add static UI regression coverage for the project creation request guard.

Out of scope:

- Changing workspace/project backend APIs, membership policy, permissions,
  invitation flow, canonical document storage, or append-only
  `document_events` semantics.
- Changing ZIP import, document create/save, rollback, replay, comments,
  reviews, WebSocket payloads, or deployment settings.
- Persisting browser project-create request state across reloads.
