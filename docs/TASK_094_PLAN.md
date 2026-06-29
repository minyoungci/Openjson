# TASK_094_PLAN.md

## Objective

Add a read-only editor screen state-machine contract to `editor-state` so a
frontend can implement the non-realtime shared JSON editor consistently.

## Scope

- Extend `GET /documents/{document_id}/editor-state`.
- Add `workflow.state_machine`.
- Define stable client/editor states:
  - `read_only`
  - `clean`
  - `dirty`
  - `syntax_invalid`
  - `previewing`
  - `preview_ready`
  - `saving`
  - `saved`
  - `validation_failed`
  - `stale_conflict`
  - `conflict_preview`
- Define allowed actions and transitions for the non-realtime editor flow.
- Derive persistence-capable states from existing RBAC capabilities.

## Policy

- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, automatic
  merge/conflict resolution, or complex path-level permissions.
- The state machine is metadata only. It is not stored in the database and does
  not create document events, update snapshots, increment versions, write audit
  rows, or persist validation state.
- Local states such as `dirty`, `syntax_invalid`, `previewing`, and `saving`
  are client-owned.
- Server-verified states such as `clean`, `preview_ready`, `saved`,
  `validation_failed`, `stale_conflict`, and `conflict_preview` map to existing
  API outcomes.
- Only accepted save success creates a document event. Preview, conflict
  preview, syntax errors, validation failures, version conflicts, and reloads
  never create events.

## Verification

- Owner/editor-style actors start in `clean` and can reach preview/save states.
- Viewer actors start in `read_only` and cannot persist.
- The state machine exposes explicit transition rules for local edits,
  previews, saves, validation failures, and version conflicts.
- HTTP shared-edit smoke verifies the state-machine metadata from a live
  server.
