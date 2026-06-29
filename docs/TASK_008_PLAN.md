# TASK_008 Plan: Minimal Audit Log

TASK_008 adds a minimal append-only audit log for sensitive operational events.

This task does not add full authentication, password login, token issuance,
invitation flow, email delivery, workspace role tables, billing, UI work,
realtime collaboration, WebSocket, Git integration, branching, pull requests,
AI features, offline sync, webhook delivery, audit export, automatic
merge/conflict resolution, or complex path-level permissions.

## Scope

- Add an append-only `audit_log` table.
- Record accepted project membership management operations.
- Record rejected project membership management attempts.
- Add project-scoped audit log read API for owners/admins.
- Keep document mutation history in `document_events`.
- Keep operational/security audit in `audit_log`.

## API Endpoint

- `GET /projects/{project_id}/audit-log`

All requests require `X-Actor-Id`.

## Permission Policy

- `owner`, `admin`: read project audit log
- `editor`, `reviewer`, `viewer`: no audit log read access

## Data Model

`audit_log`:

- `id`
- `actor_id` nullable text
- `workspace_id` nullable text
- `project_id` nullable text
- `document_id` nullable text
- `action`
- `target_type`
- `target_id` nullable text
- `outcome`: `success` or `failure`
- `error_code` nullable text
- `details` JSON text
- `created_at`

The audit table intentionally stores IDs as text without foreign keys so failed
attempts against missing actors or missing resources can still be audited.

## Integrity Policy

- `audit_log` is append-only.
- Accepted membership change and success audit row commit together.
- Rejected membership attempts write failure audit rows without mutating
  `project_members`.
- Audit logging must not create `document_events`.

## Tests

- successful member add/update/remove creates success audit rows
- rejected member management attempts create failure audit rows
- audit log is append-only at the DB level
- audit read is owner/admin only
- HTTP audit route returns standard error envelope for denied users
- migration creates audit table and triggers idempotently
