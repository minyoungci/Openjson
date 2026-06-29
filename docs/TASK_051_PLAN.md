# TASK_051 Plan - SQLite Restore Manifest Edge Cases

## Goal

Lock down restore behavior for malformed or missing SQLite backup manifests.

TASK_050 added adjacent manifest verification before restore. This task makes
the edge-case policy explicit and adds regression coverage so restore cannot
silently create a target DB from an unverifiable or malformed manifest state.

## Non-Goals

- No production backup scheduler.
- No encryption, remote object storage, retention policy, or disaster recovery
  SLA.
- No DB schema change.
- No document/event/snapshot repair.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## Behavior

If an adjacent manifest exists but is malformed JSON:

- restore returns `status=failed`
- `manifest_verification.status` is `failed`
- JSON decoder details are returned under `manifest_verification.details`
- target DB is not created or overwritten
- CLI exits non-zero

If an adjacent manifest is missing:

- restore remains backward-compatible and proceeds
- `manifest_verification.status` is `not_found`
- post-restore database integrity checks still run
- CLI exit still depends on restored database integrity

## Data Model

No schema change.

This is a local/staging operational safety policy only.

## Tests

- Malformed manifest JSON fails before target DB creation.
- Malformed manifest JSON CLI exits non-zero with the failed verification
  payload.
- Missing manifest restore succeeds with `manifest_verification.status` set to
  `not_found`.
