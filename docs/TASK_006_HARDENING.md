# TASK_006 Hardening

This document records the TASK_006 hardening policy for minimal user,
workspace, and project APIs.

TASK_006_HARDENING does not add full authentication, password login, token
issuance, invitation flow, workspace role tables, billing, UI work, realtime
collaboration, WebSocket, Git integration, branching, pull requests, AI
features, offline sync, automatic merge/conflict resolution, or complex
path-level permissions.

## Scope

- Verify bootstrap APIs through actual FastAPI HTTP request handling.
- Keep error responses in the standard `{ "error": ... }` envelope.
- Verify project creation transaction rollback if owner membership insertion
  fails.
- Add standard `docs/API_SPEC.md` and `docs/DATA_MODEL.md` entrypoints for the
  currently implemented backend scope.
- Explicitly list `httpx` as a dependency because FastAPI/Starlette TestClient
  requires it for HTTP-level tests.

## HTTP Error Policy

The minimal workspace/project API must use the same error envelope as document,
schema, comment, and review APIs:

```json
{
  "error": {
    "code": "AUTH_REQUIRED",
    "message": "Request requires actor information.",
    "details": {}
  }
}
```

Request validation errors from FastAPI are normalized to `INVALID_JSON_SYNTAX`
for consistency with the existing TASK_001 error policy.

## Transaction Policy

`POST /workspaces/{workspace_id}/projects` creates both:

- `projects` row
- `project_members` owner row

Both writes must commit or roll back together. If project membership insertion
fails after the project insert, the project row must not remain.

## Documentation Policy

`docs/API_SPEC.md` and `docs/DATA_MODEL.md` now exist as standard entrypoints.
They summarize the currently implemented backend scope and point to task
baseline documents for details.

## Tests

Hardening tests cover:

- HTTP bootstrap flow from user to workspace to project
- HTTP error envelope for missing actor, duplicate user, and malformed request
- project creation rollback when owner membership insertion fails
- route coverage remains intact
