# TASK_006 Plan: Minimal Workspace and Project API

TASK_006 adds the minimal backend APIs needed to create users, workspaces, and
projects without relying only on `scripts/seed_dev.py`.

This task does not add full authentication, invitation flow, workspace roles,
SSO, billing, UI work, realtime collaboration, WebSocket, Git integration,
branching, pull requests, AI features, offline sync, or complex path-level
permissions.

## Scope

- Create user records for local/API bootstrap.
- Create workspaces owned by an existing actor.
- List workspaces accessible to an actor.
- Read a workspace if the actor owns it or belongs to at least one project in it.
- Create projects under a workspace owned by the actor.
- Automatically add the project creator as project `owner`.
- List projects visible to an actor.
- Read project detail for project members.

## API Endpoints

- `POST /users`
- `POST /workspaces`
- `GET /workspaces`
- `GET /workspaces/{workspace_id}`
- `POST /workspaces/{workspace_id}/projects`
- `GET /workspaces/{workspace_id}/projects`
- `GET /projects/{project_id}`

All endpoints except `POST /users` require `X-Actor-Id`.

## Permission Policy

- `POST /users` is public bootstrap only; it does not create sessions or tokens.
- Workspace create requires an existing actor.
- Workspace read/list requires workspace ownership or project membership.
- Project create requires workspace ownership.
- Project read requires project membership.

The task intentionally does not implement workspace member tables or invitation
management. Project-level RBAC remains the enforcement boundary for document,
schema, comment, and review APIs.

## Data Model Changes

No new tables are required.

Indexes may be added for lookup efficiency:

- `idx_workspaces_owner`
- `idx_projects_workspace`

Existing `project_members` stores project-level roles.

## Integrity Policy

Project creation and owner membership insertion happen in the same transaction.
If membership insertion fails, the project row is rolled back.

## Tests

- user creation and duplicate email rejection
- workspace creation by existing actor
- workspace list/access rules
- project creation creates owner membership
- project member can read project
- non-owner workspace actor cannot create projects
- routes are registered
