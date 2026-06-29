# TASK_096_PLAN.md

## Objective

Add a local, non-realtime JSON workspace editor shell on top of the existing
versioned document APIs.

This is the first usable UI surface for loading a project, selecting JSON
documents, editing raw JSON text, validating, previewing, saving, inspecting
history/diff, and rolling back through the existing backend contracts.

## Explicit Non-Scope

This task does not implement realtime collaboration, WebSocket, presence,
offline sync, merge/conflict auto-resolution, Git integration, branching, pull
requests, AI features, full authentication, invitation flow, or complex
path-level permissions.

## UI Boundary

The UI is served by FastAPI as static files:

- `GET /`
- `GET /app`
- `GET /static/styles.css`
- `GET /static/app.js`

It uses the existing local development auth boundary:

- `X-Actor-Id` for local dev users.
- Optional `Authorization: Bearer <project token>` for project-scoped API
  token flows.

The UI does not create its own persisted frontend state. Browser-local form
values may be stored in `localStorage`, but canonical project/document state
remains in SQLite through the existing backend APIs.

## Backend Contracts Used

- `GET /projects/{project_id}/editor-bootstrap`
- `POST /projects/{project_id}/documents`
- `GET /documents/{document_id}/editor-state`
- `POST /documents/{document_id}/validate`
- `POST /documents/{document_id}/content-preview`
- `POST /documents/{document_id}/content-conflict-preview`
- `PUT /documents/{document_id}/content`
- `GET /documents/{document_id}/history`
- `GET /documents/{document_id}/diff`
- `POST /documents/{document_id}/rollback`

Accepted saves still go through `PUT /documents/{document_id}/content`, which
generates JSON Patch operations and persists normal append-only
`document_events` update rows. Syntax-invalid editor buffers are kept local and
must not become canonical latest snapshots.

## Verification

- Static UI routes return the expected HTML/CSS/JS assets.
- The JavaScript references the non-realtime editor bootstrap, content save,
  conflict preview, history, diff, and rollback endpoints.
- Serving the UI does not create document events or document rows.
- Existing backend tests and the non-realtime shared edit HTTP smoke remain the
  source of truth for mutation/replay behavior.

