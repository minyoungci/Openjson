# TASK_086_PLAN.md

## Objective

Harden the non-realtime shared editing save contract by returning the
append-only event metadata created by accepted document mutations.

## Scope

- Accepted mutation responses for:
  - `POST /projects/{project_id}/documents`
  - `PATCH /documents/{document_id}`
  - `DELETE /documents/{document_id}`
  - `POST /documents/{document_id}/restore`
  - `POST /documents/{document_id}/rollback`
- Two-actor non-realtime edit-flow tests using:
  - `GET /documents/{document_id}/editor-state`
  - `POST /documents/{document_id}/patch-preview`
  - `PATCH /documents/{document_id}`

## Policy

- Every accepted document mutation still creates exactly one append-only
  `document_events` row.
- The mutation response includes:
  - `event_id`
  - `event_type`
- The returned `event_id` must identify the event row that actually records the
  accepted mutation.
- Conflict responses remain `VERSION_CONFLICT` and must not create events.
- Patch preview remains read-only and must not return persisted event metadata.
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, automatic
  merge/conflict resolution, or complex path-level permissions.

## Verification

- Add coverage for create, patch, delete, restore, and rollback response event
  metadata matching history rows.
- Add a two-actor shared edit flow:
  - both actors load editor-state at version 1
  - actor A saves a patch
  - actor B's stale preview/save fails with `VERSION_CONFLICT`
  - no event is written for the conflict
  - actor B reloads editor-state and saves with the new base version
  - replay still reconstructs the latest snapshot
- Run focused document/editor tests and the full test suite.
