# TASK_112 Plan: Production Entry UX Cleanup

## Objective

Tighten the static app entry flow for real users:

1. Sign up or log in.
2. Select an existing project or open a dedicated project creation mode.
3. Enter the JSON workspace editor.

This task removes remaining developer-oriented identity fallback paths from the
static UI. Backend development compatibility with `X-Actor-Id` remains
unchanged for tests and API smoke commands, but the official browser app should
authenticate with local session bearer tokens only.

## Scope

- Remove hidden actor/project/token connection form markup from the static UI.
- Remove `X-Actor-Id` fallback request headers from `static/app.js`.
- Store the authenticated user id only as browser UI state for labels such as
  "You", not as an API identity fallback.
- Split the project home into a project list mode and a dedicated project
  creation mode.
- Keep project invitation acceptance as the user-facing team join path.
- Update workflow documentation and static UI regression tests.

## Out of Scope

- Backend auth model changes.
- Removing `X-Actor-Id` support from API tests or local smoke scripts.
- Billing, SSO policy administration, branching, pull requests, Git
  integration, AI features, or complex path-level permissions.
- Replacing the append-only document event model.

## Data Model

No schema change.

## API

No endpoint change. The static browser app uses existing session bearer token
authentication.

## Test Plan

- Static UI route test confirms the public app still loads without mutating the
  database.
- Static UI regression test confirms project list/create modes exist.
- Static UI regression test confirms browser JS no longer sends `X-Actor-Id`
  fallback headers.
