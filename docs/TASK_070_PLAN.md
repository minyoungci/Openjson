# TASK_070 Plan - Strict Document Path Prefix Filters

## Goal

Make project document `path_prefix` read filters use the same relative POSIX
path rules as canonical document paths and match path segments rather than raw
string prefixes.

`path_prefix=config` should match `config/model.json`, not
`configurations/model.json`.

## Non-Goals

- No persistent folder table.
- No document rename or move API.
- No search index.
- No DB schema change.
- No document/event/snapshot mutation.
- No UI work.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Covered Surfaces

- `GET /projects/{project_id}/documents?path_prefix=...`
- `GET /projects/{project_id}/document-tree?path_prefix=...`

## Behavior

- omitted or blank `path_prefix` means no prefix filter
- a single trailing `/` is accepted and normalized away
- leading or trailing whitespace is rejected
- Windows-style `\` separators are rejected
- absolute prefixes starting with `/` are rejected
- empty segments, `.` segments, and `..` segments are rejected
- document listing matches either the exact path or a child segment
- document tree remains read-only and roots at the normalized prefix

## Data Model

No schema change.

The implementation adds a shared path-prefix validator and keeps these surfaces
as read-only derived views over `json_documents`.

## Tests

- Document list `path_prefix` matching is segment-aware.
- Document list rejects malformed path prefixes without mutation.
- Document tree rejects malformed path prefixes without mutation.
- HTTP list/tree routes return the standard error envelope for malformed
  prefixes.
