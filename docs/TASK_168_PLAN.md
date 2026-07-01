# TASK_168 Plan - Guard stale document create responses

Goal: prevent delayed browser document-create responses or failures from
clearing the current create form or loading a document into the wrong project
after the user switches projects, switches documents, closes the create panel,
or edits the create form while the request is in flight.

Scope:

- Add a browser request id for create-document actions.
- Track transient `creatingDocument` state so create cannot overlap with other
  busy editor actions.
- Capture project id, selected document id, candidate full path, content text,
  and explicit schema id before calling `POST /projects/{project_id}/documents`.
- Apply successful create responses only while the request id, project id,
  selected document id, visible create panel, path, content text, and schema
  selection still match the captured context.
- Ignore stale create failures instead of rendering them into the active create
  or validation panels.
- Invalidate outstanding create requests when project/session state changes,
  selected document changes, the create panel closes, the create form changes,
  or a JSON file is imported into the create form.
- Add static UI regression coverage for the create request guard.

Out of scope:

- Changing document create backend APIs, schema validation, path conflict rules,
  permissions, or append-only `document_events` semantics.
- Changing ZIP import, rollback, replay, realtime collaboration, or review
  workflow.
- Persisting browser create request state across reloads.
