# TASK_052 Plan - Membership Audit Atomicity Tests

## Goal

Prove that accepted project membership changes and their success audit rows are
atomic.

TASK_008 requires successful member add/update/remove operations to commit the
membership mutation and success `audit_log` row together. If the success audit
write fails, the membership mutation must roll back and only the rejected
attempt should be recorded as a failure audit row.

## Non-Goals

- No new membership endpoint.
- No audit workflow expansion.
- No DB schema change.
- No document/event/snapshot mutation.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## Covered Operations

- `add_project_member`
- `update_project_member`
- `remove_project_member`

## Behavior

When the success audit write fails:

- the membership mutation is rolled back
- a failure audit row is recorded for the rejected attempt
- no success audit row is committed
- no document event is created

## Data Model

No schema change.

This task only adds regression coverage for the existing transaction boundary.

## Tests

- Forced success audit failure during member add does not insert the member.
- Forced success audit failure during member update preserves the previous role.
- Forced success audit failure during member remove preserves the member.
- Each forced failure records a failure audit row and no success row.
