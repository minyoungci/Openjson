# TASK_144_PLAN.md

## Goal

Keep each user's project document tree in sync when other team members create,
import, delete, or restore JSON documents.

Document-scoped WebSockets already cover checkpoint, comment, and lifecycle
updates for the currently open document. This task adds a project-scoped
operational channel so the browser can refresh the project document list and
tree when the set of active documents changes.

## Scope

- Add `WS /ws/projects/{project_id}/workspace`.
- Authenticate the project WebSocket with the same session token, API token,
  or local actor fallback policy as document WebSockets.
- Require project `document:read` permission before connecting.
- Broadcast `project.documents.changed` after successful document create.
- Broadcast `project.documents.changed` after successful ZIP import apply.
- Broadcast `project.documents.changed` after successful document delete and
  restore.
- Make the static browser client refresh project bootstrap state when it
  receives a project document-set update and the current editor buffer is
  clean.
- Preserve unsaved local editor buffers by delaying automatic project refresh
  while the current editor is dirty.

## Exclusions

- Do not add new database tables.
- Do not change append-only `document_events`, snapshots, replay, rollback, or
  ZIP import transaction semantics.
- Do not implement branching, pull requests, Git integration, AI features,
  review workflow changes, or complex path-level permissions.

## Verification

```powershell
python -W ignore::DeprecationWarning -m unittest tests.test_realtime_collaboration tests.test_static_ui
python -W ignore::DeprecationWarning -m compileall app
python -W ignore::DeprecationWarning -m unittest discover -s tests
```
