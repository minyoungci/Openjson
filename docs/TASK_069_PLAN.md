# TASK_069 Plan - Schema Match Full Path Validation Parity

## Goal

Use the same relative POSIX document path policy for schema match previews that
document creation uses for canonical `json_documents.full_path` values.

Schema match preview is read-only, but it predicts how schema binding will work
for a document path. If it accepts paths that document creation rejects, clients
can see misleading preview results for paths that can never become canonical
documents.

## Non-Goals

- No schema binding priority changes.
- No schema update or deactivate API.
- No DB schema change.
- No persistent schema match rows.
- No document/event/snapshot mutation.
- No UI work.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Behavior

`GET /projects/{project_id}/schema-matches?full_path=...` now rejects the same
ambiguous document path forms rejected by document creation:

- empty or whitespace-only paths
- leading or trailing whitespace
- Windows-style `\` separators
- absolute paths starting with `/`
- paths ending with `/`
- empty path segments
- `.` and `..` segments

The endpoint remains read-only. Rejected preview requests do not create or
change schemas, documents, document events, or audit log entries.

## Data Model

No schema change.

The implementation adds a small shared path validation helper so document
creation and schema match preview cannot drift.

## Tests

- Service-level schema match preview rejects invalid `full_path` forms without
  mutation.
- HTTP schema match preview rejects invalid `full_path` forms with the standard
  `INVALID_REQUEST` error envelope.
- Existing valid schema match preview behavior continues to work.
