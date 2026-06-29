# TASK_093_PLAN.md

## Objective

Add an editor workflow contract to the read-only editor-state response so a
frontend can build the non-realtime shared JSON document editor without
hard-coding endpoint order or save semantics.

## Scope

- Extend `GET /documents/{document_id}/editor-state`.
- Add a top-level `workflow` block.
- Describe reload, validation, preview, content conflict preview, save,
  history, diff, and rollback actions.
- Derive action availability from the actor's existing project RBAC
  capabilities.

## Policy

- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, automatic
  merge/conflict resolution, or complex path-level permissions.
- `workflow` is read-only metadata. It does not create document events, update
  snapshots, increment versions, write audit rows, or persist validation state.
- Accepted saves still require `base_version`, still reject stale versions with
  `VERSION_CONFLICT`, and still create append-only `document_events`.
- The canonical persisted source remains `document.content`; raw editor text is
  a projection through `document.content_text`.
- `content-conflict-preview` remains a diagnostic/recovery step. It does not
  apply or auto-merge stale changes.

## Workflow Fields

- `mode = non_realtime_versioned_edit`
- `canonical_source = document.content`
- `raw_text_source = document.content_text`
- `base_version_field = base_version`
- `required_base_version`
- `supported_content_sources = ["content", "content_text"]`
- `save_contract`
- `actions`

## Verification

- Owner/editor-style actors see available preview/save actions.
- Viewer actors see read-only actions available and mutation actions
  unavailable.
- Workflow endpoints point to the current document id.
- Workflow reads do not mutate event counts, snapshots, versions, audit rows,
  or replay consistency.
