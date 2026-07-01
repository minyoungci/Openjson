# TASK_111 Plan: Team Workspace Smoke

## Goal

Add one end-to-end smoke command that verifies the deployed or local service can
support the practical team workflow OpenJson is targeting.

## Scope

- Sign up an owner and invited teammate.
- Create a workspace and project.
- Create and accept a project invitation.
- Verify project member names and roles are visible through the API.
- Create a JSON document through the canonical document create endpoint.
- Load editor state as both users.
- Save a teammate edit through the canonical content endpoint.
- Verify collaboration-state reports the accepted checkpoint.
- Create a document/path note, add a reply, resolve it, and reopen it.
- Verify notes do not mutate document versions.
- Verify diff and replay consistency after the team edit.

## Out of Scope

- New product tables or API endpoints.
- Browser UI automation.
- Git integration, branching, pull requests, AI features, billing, or complex
  path-level permissions.
- Replacing existing TASK_103/TASK_104 WebSocket and offline-sync smokes.

## Data Model

No schema change. The smoke validates existing auth, invitation, document,
comment, collaboration-state, diff, and replay surfaces.

## API

No API change. The smoke uses existing public REST endpoints only.

## Test Plan

- Unit-test the smoke runner against FastAPI `TestClient`.
- Assert final document version, member roles, checkpoint metadata, note thread
  status, diff paths, and replay status.
- Run the script against a local server or official deployed URL before release
  when needed.
