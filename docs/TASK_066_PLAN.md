# TASK_066 Plan - Strict JSON Pointer Read Filters

## Goal

Pin down strict JSON Pointer validation on read-only path filters.

TASK_065 made shared JSON Pointer parsing reject malformed escape sequences.
This task adds regression coverage for read-only filters that rely on that
parser so malformed paths cannot silently produce misleading empty reads.

## Non-Goals

- No query language expansion.
- No persistent search index.
- No DB schema change.
- No document/event/snapshot mutation.
- No document editor UI.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Covered Surfaces

- `GET /projects/{project_id}/document-search?path=...`
- `GET /projects/{project_id}/document-events?changed_path=...`

## Behavior

- valid escaped JSON Pointer filters continue to work
- invalid escaped filters such as `/a~2b` return `INVALID_REQUEST`
- trailing `~` in a filter returns `INVALID_REQUEST`
- rejected read filters create no document events
- rejected read filters do not mutate latest snapshots

## Data Model

No schema change.

This task only adds regression coverage for existing read-only filter
validation.

## Tests

- Project document search rejects malformed JSON Pointer escape filters without
  mutation.
- Project document event feed rejects malformed JSON Pointer escape filters
  without mutation.
