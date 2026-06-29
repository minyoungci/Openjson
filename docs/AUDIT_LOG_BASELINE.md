# Audit Log Baseline

This document records the TASK_008 minimal audit log baseline.

The audit log is not a replacement for `document_events`. Document changes
remain audited through append-only document events with patches, inverse
patches, before/after values, and replay consistency.

`audit_log` records sensitive operational events that are not JSON document
mutations, starting with project membership management.

TASK_008 does not add full authentication, password login, token issuance,
invitation flow, email delivery, workspace role tables, billing, UI work,
realtime collaboration, WebSocket, Git integration, branching, pull requests,
AI features, offline sync, webhook delivery, audit export, automatic
merge/conflict resolution, or complex path-level permissions.

## API

- `GET /projects/{project_id}/audit-log`

All requests require `X-Actor-Id`.

## Permission Policy

- `owner`, `admin`: read project audit log
- `editor`, `reviewer`, `viewer`: cannot read audit log

## Logged Events

TASK_008 logs:

- successful project member add/update/remove
- rejected project member add/update/remove attempts

## Append-Only Policy

`audit_log` rows are append-only.

SQLite triggers reject direct updates and deletes:

- `trg_audit_log_no_update`
- `trg_audit_log_no_delete`

## Failure Policy

Rejected membership attempts must leave no partial membership mutation.

Failure audit rows include:

- action
- actor id when supplied
- project id when supplied
- target user id when supplied
- error code
- details JSON

## Document Event Separation

Audit log writes must not create `document_events` and must not change document
snapshots or versions.

The document replay invariant remains:

```text
Replay(DocumentEvent[0..N]) == json_documents.current_snapshot_json
```

See `docs/TASK_052_PLAN.md` for membership success audit atomicity regression
coverage.
