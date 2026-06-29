# TASK_095_PLAN.md

## Objective

Add a read-only project editor bootstrap API that gives a frontend enough
metadata to render the first project editor screen without guessing multiple
backend contracts.

This task does not add UI, realtime collaboration, WebSocket, offline sync,
merge automation, Git integration, branching, pull requests, AI features, or
complex path-level permissions.

## API

`GET /projects/{project_id}/editor-bootstrap`

Query parameters:

- `selected_document_id` optional active document id to include through the
  existing editor-state shape.
- `include_validation` defaults to `true` and is forwarded to the selected
  document editor-state.
- `recent_events_limit` defaults to `10`, accepts `0..50`, and is forwarded to
  the selected document editor-state.
- `include_deleted` defaults to `false` for the project document list and tree.
- `path_prefix` filters both list and tree with the existing strict relative
  POSIX path-prefix policy.
- `q` filters only the flat project document list.
- `limit` and `offset` page the flat project document list.

## Response Shape

The response includes:

- `project`: project metadata and actor role.
- `actor`: actor id, role, and editor capabilities.
- `bootstrap`: read-only contract metadata and available read actions.
- `documents`: the same paged metadata list as
  `GET /projects/{project_id}/documents`.
- `document_tree`: the same folder-like tree as
  `GET /projects/{project_id}/document-tree`.
- `selected_document_editor_state`: `null` unless `selected_document_id` is
  provided. When provided, this is derived from
  `GET /documents/{document_id}/editor-state`.

## Rules

- The API requires project `DOCUMENT_READ` permission.
- API tokens remain project-scoped.
- A selected document must belong to the requested project and must not be
  soft-deleted.
- The API is read-only and must not create document events, update snapshots,
  increment versions, write audit rows, or persist validation results.
- The selected document editor-state preserves the non-realtime versioned edit
  contract: accepted saves still go through document mutation APIs with
  `base_version` and append-only `document_events`.

## Tests

- Project bootstrap returns project, actor, document list, tree, and selected
  document editor-state without mutation.
- Bootstrap without a selected document returns a null selected editor state.
- Viewer bootstrap is read-only and exposes viewer editor capabilities.
- Selected documents outside the project or soft-deleted selected documents are
  rejected as `DOCUMENT_NOT_FOUND`.
- Invalid `recent_events_limit`, `limit`, `offset`, `path_prefix`, and `q`
  values are rejected as `INVALID_REQUEST`.
- HTTP route and project-scoped bearer token access are covered.

