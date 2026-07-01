# TASK_164 Plan - Guard stale project document-change refresh status

Goal: prevent delayed `project.documents.changed` browser refresh handlers from
writing a project-document update status into the current editor after the user
switches projects, switches documents, starts editing, or a newer project
document-change refresh supersedes it.

Scope:

- Add a browser request id for project document-change refresh handling.
- Capture project id and selected document id before refreshing bootstrap state
  in response to `project.documents.changed`.
- Keep delaying automatic refresh while the editor buffer is dirty.
- After the refresh finishes, write `Project documents updated.` only while the
  request id, project id, selected document id, and clean editor state still
  match the captured context.
- Invalidate outstanding project document-change refresh UI updates when
  returning to project selection, opening another project, clearing session
  state, clearing the selected editor, or detaching from a live-deleted selected
  document.
- Add static UI regression coverage for the guarded status update.

Out of scope:

- Changing server WebSocket payload shape.
- Adding a project event store.
- Changing document create, ZIP import, delete, restore, rollback, replay,
  schema validation, or append-only `document_events` semantics.
- Persisting browser project document-change request state across reloads.
