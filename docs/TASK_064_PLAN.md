# TASK_064 Plan - Concrete Array Append Changed Paths

## Goal

Store concrete changed paths for array append updates.

User-submitted JSON Patch-like append operations use the request path
`/array/-`, but `-` is not a concrete JSON Pointer location in the resulting
document. Document events should record the actual appended index so history,
event feeds, filters, blame, and audit reads can target the path that exists in
the accepted snapshot.

## Non-Goals

- No new patch operation support.
- No JSON Patch move, copy, or test support.
- No array identity or merge algorithm.
- No DB schema change.
- No migration or rewrite of existing stored events.
- No document editor UI.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No complex path-level permission model.

## Covered Endpoint

- `PATCH /documents/{document_id}`

## Behavior

For accepted array append updates:

- request patch may still use `/items/-`
- stored inverse patch uses the concrete appended path
- stored `changed_paths` uses the concrete appended path
- stored `before_values` and `after_values` use the concrete appended path
- project document event feed `changed_path` filters match the concrete path
- `changed_path=/items/-` does not match the stored append event

## Data Model

No schema change.

This task only improves event metadata generated for newly accepted append
events. Existing persisted events are not rewritten.

## Tests

- Array append event metadata records the concrete appended path.
- Project document event feed filtering uses the concrete appended path.
