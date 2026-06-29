# TASK_047 Plan - Audit Log Details JSON Diagnostics

## Goal

Make persisted `audit_log.details` JSON diagnosable on read-only surfaces.

Normal audit writes serialize details through the service layer, but a local
database can still be corrupted manually. Owner/admin read surfaces should stay
usable and report the malformed field instead of crashing or mutating
append-only audit rows.

## Non-Goals

- No audit workflow expansion.
- No audit export file generation.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.
- No DB schema change.
- No repair or rewrite of immutable audit rows.

## Covered Surfaces

- `GET /projects/{project_id}/audit-log`
- `GET /projects/{project_id}/activity`
- `GET /projects/{project_id}/export?include_audit_log=true`

## Behavior

For audit-log read/export/activity responses:

- audit metadata remains readable
- malformed `details` is returned as `null`
- the affected audit payload includes `details_error`
- diagnostic fields include field, message, line, column, and position

## Data Model

No schema change.

`audit_log` remains append-only. This task only changes how malformed persisted
details JSON is reported.

## Tests

- Project audit log returns malformed details as `null` with `details_error`.
- Project activity returns malformed audit details as `null` with
  `details_error`.
- Project export returns malformed audit details as `null` with
  `details_error`.
- HTTP audit/activity/export surfaces preserve successful response envelopes for
  malformed audit details.
