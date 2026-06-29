# RBAC Baseline

This document records the approved TASK_003 minimal project-level RBAC policy.

TASK_003 does not add path-level permissions, SSO, invitation flow, comments,
review workflow, realtime collaboration, UI, WebSocket, offline sync, branching,
pull requests, Git integration, or AI features.

## Membership Model

Project membership is stored in `project_members`:

- `id`
- `project_id`
- `user_id`
- `role`
- `created_at`

`(project_id, user_id)` is unique.

Allowed roles:

- `owner`
- `admin`
- `editor`
- `reviewer`
- `viewer`

Existing databases are migrated idempotently by backfilling each project with
the owning workspace user as `owner`.

## Permission Matrix

| Role | Document read | Document create/patch/delete | Restore | Rollback | Validate | Schema read | Schema create | Comment read | Comment write | Review read | Review create | Review decide | Review apply | Member read | Member manage | Audit read |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| owner | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| admin | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| editor | Yes | Yes | No | Yes | Yes | Yes | No | Yes | Yes | Yes | Yes | No | Yes | Yes | No | No |
| reviewer | Yes | No | No | No | Yes | Yes | No | Yes | Yes | Yes | No | Yes | No | Yes | No | No |
| viewer | Yes | No | No | No | No | Yes | No | Yes | No | Yes | No | No | No | Yes | No | No |

## Enforcement Policy

All project-scoped document and schema APIs require an actor identity. Local
development can pass `X-Actor-Id`; TASK_012 also allows `Authorization: Bearer
<token>` for a project-scoped API token.

API tokens act as their owning user and do not bypass project RBAC. A token can
only access the project it was created for.

The service checks:

1. Actor header is present.
2. Actor exists.
3. Project exists.
4. Actor has a membership row for the project.
5. Actor role includes the required permission.

The MVP remains project-level only. It intentionally does not implement
path-level permissions.

## Error Policy

- Missing actor: `AUTH_REQUIRED`
- Unknown actor: `PERMISSION_DENIED`
- Non-member actor: `PERMISSION_DENIED`
- Insufficient role: `PERMISSION_DENIED`

Permission errors must not create document events, change snapshots, or increment
document versions.

Comment permission errors must not create comment threads or comments.

Review permission errors must not create review requests, review decisions, or
document events.

Membership management permission errors must not create, update, or delete
`project_members` rows.

Membership management permission errors are recorded in `audit_log` as failure
events when the request reaches the service layer.

## Data Integrity Policy

RBAC is a gate before mutation writes.

RBAC must not weaken TASK_001/TASK_002 invariants:

- accepted document mutations still create append-only `document_events`
- rejected mutations create no event
- rejected mutations do not change snapshots
- rollback remains a new event
- schema validation still happens before event insert
- replaying events reconstructs the latest snapshot exactly
- comment metadata does not create document events or mutate document snapshots
- review metadata does not create document events or mutate document snapshots until approved apply
- membership changes do not create document events or mutate document snapshots
- audit log writes do not create document events or mutate document snapshots
- API token create/revoke does not create document events or mutate document
  snapshots
- restore is recorded as a new document event and does not delete prior history

See `docs/PROJECT_MEMBERSHIP_BASELINE.md` for the approved TASK_007 project
membership policy.

See `docs/AUDIT_LOG_BASELINE.md` for the approved TASK_008 minimal audit log
policy.

See `docs/AUTH_BASELINE.md` for the approved TASK_012 project-scoped API token
boundary.
