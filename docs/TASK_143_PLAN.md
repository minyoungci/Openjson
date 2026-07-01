# TASK_143_PLAN.md

## Goal

Notify active document WebSocket clients when a document is soft-deleted or
restored.

Accepted patch, content, and rollback mutations already broadcast fresh
checkpoint state. Delete and restore are lifecycle mutations, so clients also
need an operational signal when the currently open document leaves or re-enters
the active document set.

## Scope

- Broadcast `document.lifecycle` after a successful `DELETE /documents/{id}`.
- Broadcast `document.lifecycle` after a successful
  `POST /documents/{id}/restore`.
- Include the lifecycle event metadata returned by the existing mutation
  pipeline: `event_id`, `event_type`, `previous_version`, `current_version`,
  `deleted_at`, and `full_path`.
- Make the static browser client react to lifecycle updates for the selected
  document.
- Preserve an unsaved local editor buffer if the selected document is deleted
  remotely.

## Exclusions

- Do not change document event storage, snapshot replay, or lifecycle
  transaction semantics.
- Do not add project-level WebSocket channels.
- Do not implement branching, pull requests, Git integration, AI features,
  review workflow changes, or complex path-level permissions.

## Verification

```powershell
python -W ignore::DeprecationWarning -m unittest tests.test_realtime_collaboration tests.test_static_ui
python -W ignore::DeprecationWarning -m compileall app
python -W ignore::DeprecationWarning -m unittest discover -s tests
```
