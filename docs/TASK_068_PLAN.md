# TASK_068 Plan - Strict Document Full Path Validation

## Goal

Make canonical document `full_path` values unambiguous before documents enter
the snapshot and event-log model.

Document paths drive listing, tree construction, export paths, search matches,
schema pattern binding, and future editor navigation. They should be stored as
relative POSIX-style paths, not absolute paths or paths with ambiguous
segments.

## Non-Goals

- No folder table.
- No document rename API.
- No path-level permission model.
- No UI work.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.

## Behavior

Document create rejects `full_path` values that are:

- empty or whitespace-only
- not strings
- leading or trailing whitespace
- Windows-style paths containing `\`
- absolute paths starting with `/`
- paths ending with `/`
- paths containing empty segments, such as `config//model.json`
- paths containing `.` or `..` segments

Rejected paths create no `json_documents` row and no `document_events` row.

## Data Model

No schema change.

This task tightens application-level validation before insertion. Existing
database uniqueness constraints and append-only event constraints are unchanged.

## Tests

- Service-level invalid `full_path` cases are rejected before document/event
  insertion.
- HTTP document create returns the standard error envelope for invalid
  `full_path` values.
- Valid relative POSIX paths continue to work.
