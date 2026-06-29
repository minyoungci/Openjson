# TASK_071 Plan - Strict Schema File Pattern Validation

## Goal

Keep schema registry file patterns inside the same relative POSIX path boundary
as canonical document paths.

Schema `file_pattern` controls automatic document schema binding. Invalid or
ambiguous path patterns should not be stored in immutable schema rows because
those rows influence future document creation.

## Non-Goals

- No schema update or deactivate API.
- No schema binding priority changes.
- No custom pattern language beyond Python `fnmatch`.
- No DB schema change.
- No document/event/snapshot mutation.
- No UI work.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Behavior

Schema create rejects provided `file_pattern` values that are:

- empty or whitespace-only
- leading or trailing whitespace
- Windows-style `\` separators
- absolute patterns starting with `/`
- patterns ending with `/`
- patterns containing empty path segments
- patterns containing literal `.` or `..` segments

Glob segments such as `*` and `**` remain allowed. `None` still means the
schema is not used for automatic file-pattern binding.

Rejected schema create requests do not create schema rows, document rows, or
document events.

## Data Model

No schema change.

This task tightens application-level validation before immutable `schemas` rows
are inserted.

## Tests

- Service-level schema create rejects invalid `file_pattern` values without
  mutation.
- HTTP schema create rejects invalid `file_pattern` values with the standard
  error envelope.
- Valid `*` and `**` patterns continue to work.
