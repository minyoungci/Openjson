# Workspace and Project Baseline

This document records the TASK_006 minimal workspace/project API baseline.

TASK_006 is bootstrap and project-structure work only. It does not add full
authentication, password login, invitation flow, workspace role tables, billing,
UI work, realtime collaboration, WebSocket, Git integration, branching, pull
requests, AI features, offline sync, automatic merge/conflict resolution, or
complex path-level permissions.

## API

- `POST /users`
- `POST /workspaces`
- `GET /workspaces`
- `GET /workspaces/{workspace_id}`
- `POST /workspaces/{workspace_id}/projects`
- `GET /workspaces/{workspace_id}/projects`
- `GET /projects/{project_id}`

`POST /users` is public bootstrap only. It creates a user row but does not issue
tokens or sessions.

All other endpoints require `X-Actor-Id`.

## Permission Policy

- Workspace create requires an existing actor.
- Workspace read/list allows workspace owner access.
- Workspace read/list also allows a project member to see workspaces containing
  their projects.
- Project create requires workspace ownership.
- Project create automatically inserts a `project_members` owner row for the
  creator.
- Project read requires project membership.

Project-level RBAC remains the authorization boundary for documents, schemas,
comments, and reviews.

## Transaction Policy

Project row creation and owner membership insertion happen in one transaction.

If owner membership insertion fails, the project creation is rolled back.

TASK_006_HARDENING verifies this rollback behavior with a forced
`project_members` insert failure.

## Data Model

No new tables were added.

Indexes added:

- `idx_workspaces_owner`
- `idx_projects_workspace`

## Known Limitations

- No password authentication or token issuance.
- No workspace membership table.
- No invitation API.
- No project update/delete API.
- No workspace update/delete API.
- No workspace membership management API.
- Project membership management is covered separately in
  `docs/PROJECT_MEMBERSHIP_BASELINE.md`.

See `docs/TASK_006_HARDENING.md` for HTTP-level and transaction hardening.
