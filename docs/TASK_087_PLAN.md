# TASK_087_PLAN.md

## Objective

Add a developer smoke script that proves the non-realtime shared JSON edit flow
works over the HTTP API.

## Scope

- `scripts/smoke_shared_edit_flow.py`
- TestClient-backed coverage for the smoke script flow.
- DEV usage documentation for running the smoke against a local server.

## Smoke Flow

The script performs the following API sequence:

1. `GET /health`
2. `POST /users` for owner and editor actors
3. `POST /workspaces`
4. `POST /workspaces/{workspace_id}/projects`
5. `POST /projects/{project_id}/members` to add the editor
6. `POST /projects/{project_id}/documents`
7. Both actors load `GET /documents/{document_id}/editor-state`
8. Owner saves `PATCH /documents/{document_id}` at base version 1
9. Editor stale `POST /documents/{document_id}/patch-preview` fails with
   `VERSION_CONFLICT`
10. Editor stale `PATCH /documents/{document_id}` fails with
    `VERSION_CONFLICT`
11. Editor reloads editor-state, previews at the new base version, and saves
12. `GET /documents/{document_id}/history` confirms create/update/update
13. `GET /documents/{document_id}/integrity/replay` confirms replay matches
    latest snapshot

## Policy

- The script uses only the Python standard library for live HTTP.
- It creates unique smoke data by default.
- It does not add realtime collaboration, WebSocket, UI, Git integration,
  branching, pull requests, AI features, offline sync, automatic
  merge/conflict resolution, or complex path-level permissions.
- It does not add or change database schema.

## Verification

- Add tests that run the same smoke flow against FastAPI `TestClient` through a
  tiny adapter.
- Verify the smoke result reports final version 3, conflict error codes,
  create/update/update history, and replay status `ok`.
- Verify smoke assertions fail loudly on unexpected status responses.
- Run focused tests and the full test suite.
