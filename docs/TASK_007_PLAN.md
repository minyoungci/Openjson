# TASK_007 Plan: Minimal Project Membership Management

TASK_007 adds minimal project membership management for existing users.

This task does not add full authentication, password login, token issuance,
invitation flow, email delivery, workspace role tables, billing, UI work,
realtime collaboration, WebSocket, Git integration, branching, pull requests,
AI features, offline sync, automatic merge/conflict resolution, or complex
path-level permissions.

## Scope

- List project members.
- Add an existing user to a project with a project role.
- Update an existing project member role.
- Remove a project member.
- Protect projects from losing their last owner.
- Keep project-level RBAC as the authorization boundary.

## API Endpoints

- `GET /projects/{project_id}/members`
- `POST /projects/{project_id}/members`
- `PATCH /projects/{project_id}/members/{user_id}`
- `DELETE /projects/{project_id}/members/{user_id}`

All endpoints require `X-Actor-Id`.

## Permission Policy

- Any project member can list project members.
- Only `owner` and `admin` can add, update, or remove project members.
- The last project owner cannot be removed.
- The last project owner cannot be demoted to another role.

This task intentionally does not implement workspace-level membership or
path-level permission.

## Data Model Changes

No new table is required.

`project_members` already stores:

- `id`
- `project_id`
- `user_id`
- `role`
- `created_at`

TASK_007 may add an index on `(project_id, role)` for owner protection checks.

## Error Policy

- missing actor: `AUTH_REQUIRED`
- unknown actor/non-member/insufficient role: `PERMISSION_DENIED`
- missing project: `PROJECT_NOT_FOUND`
- missing target user: `USER_NOT_FOUND`
- duplicate member: `PROJECT_MEMBER_ALREADY_EXISTS`
- missing target member: `PROJECT_MEMBER_NOT_FOUND`
- invalid role or last-owner violation: `INVALID_REQUEST`

## Tests

- members can list project members.
- non-members cannot list or manage members.
- owner/admin can add existing users.
- editor/reviewer/viewer cannot manage members.
- duplicate membership is rejected.
- invalid role is rejected.
- admin can update member role.
- last owner cannot be demoted or removed.
- removing a non-last owner succeeds.
- HTTP route/error envelope coverage.
