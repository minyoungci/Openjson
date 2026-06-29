# TASK_048 Plan - Activity Document Event JSON Diagnostics

## Goal

Make project activity timeline document-event rows resilient to malformed
persisted `document_events.changed_paths` JSON.

The activity API is read-only and combines document events with audit log rows.
If one event field has been manually corrupted, owners/admins should still be
able to inspect event metadata and receive an explicit parse diagnostic.

## Non-Goals

- No event mutation, event repair, event compaction, or event deletion.
- No document mutation, audit mutation, or snapshot write.
- No DB schema change.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Surface

- `GET /projects/{project_id}/activity`

## Behavior

For malformed `document_events.changed_paths` in activity responses:

- activity row metadata remains readable
- `document_event.changed_paths` is returned as `null`
- `document_event.json_errors` includes field and JSON decoder details
- no document event, audit event, or snapshot is mutated

## Data Model

No schema change.

This is a read-only diagnostic layer over existing append-only
`document_events` rows.

## Tests

- Project activity returns malformed document-event `changed_paths` as `null`
  with `document_event.json_errors`.
- HTTP activity endpoint returns 200 and the same diagnostic payload.
- Activity read remains non-mutating when malformed event JSON is encountered.
