# TASK_106_PLAN.md

## Objective

Replace developer-oriented static UI entry points with a user-facing flow:

1. Login or sign up.
2. Create or select a project.
3. Open the JSON workspace editor.

This task is limited to the app shell and user workflow explanation. It does
not change the durable document mutation model, append-only document events,
schema validation, rollback, review workflow, or WebSocket protocol.

## UI Changes

- Remove visible Actor, Project, and Token inputs from the top bar.
- Move authentication to a dedicated first screen.
- Move workspace/project creation and project selection to a dedicated screen.
- Keep actor, project, and token values as internal application state only.
- Remove direct "create user by ID" and "add member by user ID" controls from
  the team panel.
- Keep project invitations as the user-facing team entry path.

## Persistence Policy

Saving still uses the existing document content update pipeline:

- client sends valid JSON text with `base_version`;
- server parses the JSON and derives JSON patch operations;
- server validates the candidate snapshot;
- server writes a `document_events` row;
- server updates `json_documents.current_snapshot_json` and version in the same
  accepted mutation path.

Invalid JSON, schema failures, and version conflicts must not create document
events or update the latest snapshot.

## Realtime Policy

Realtime remains checkpoint-oriented:

- presence shows who is viewing or editing the document;
- WebSocket/polling collaboration state reports newer accepted checkpoints;
- live text is transient until committed;
- durable collaboration history is still the append-only document event log.

## Comments Policy

Comments and memo threads are stored separately from JSON document content.
They can point at a file, JSON path, or change event, but resolving or adding a
comment must not mutate the canonical JSON snapshot.

## Out of Scope

- SSO configuration
- billing
- branch or pull request UI
- Git integration
- complex path-level permissions
- replacing the event-log persistence model
