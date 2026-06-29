# TASK_003 Plan: Minimal Project Membership / RBAC

TASK_003 replaces the TASK_001/TASK_002 actor-existence-only permission check
with minimal project-level membership and role-based authorization.

Do not implement path-level permissions, SSO, invitation flow, comments, review
workflow, realtime collaboration, UI, WebSocket, offline sync, branching, pull
requests, Git integration, or AI features in TASK_003.

## Scope

- Add `project_members` table.
- Support roles: `owner`, `admin`, `editor`, `reviewer`, `viewer`.
- Enforce project-level permission checks in document and schema service paths.
- Keep permissions project-scoped only.
- Update `scripts/seed_dev.py` to create owner membership for the dev project.
- Preserve TASK_001 replay and transaction invariants.
- Preserve TASK_002 schema validation auditability.

## DB Changes

Add table:

```sql
CREATE TABLE IF NOT EXISTS project_members (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'editor', 'reviewer', 'viewer')),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, user_id)
);
```

Add index:

```sql
CREATE INDEX IF NOT EXISTS idx_project_members_user
ON project_members(user_id, project_id);
```

Migration policy:

- Existing projects are backfilled with an `owner` membership for the owning workspace user.
- Backfill is idempotent with `INSERT OR IGNORE`.

## Role Policy

| Role | Document read | Document edit | Rollback | Validate | Schema read | Schema create |
|---|---:|---:|---:|---:|---:|---:|
| owner | Yes | Yes | Yes | Yes | Yes | Yes |
| admin | Yes | Yes | Yes | Yes | Yes | Yes |
| editor | Yes | Yes | Yes | Yes | Yes | No |
| reviewer | Yes | No | No | Yes | Yes | No |
| viewer | Yes | No | No | No | Yes | No |

Document edit includes create, patch, and soft delete.

## API Policy

All project-scoped document and schema APIs require `X-Actor-Id`.

Read APIs now enforce project membership:

- `GET /documents/{document_id}`
- `GET /documents/{document_id}/history`
- `GET /documents/{document_id}/diff`
- `GET /projects/{project_id}/schemas`
- `GET /schemas/{schema_id}`

Validation requires reviewer-or-higher permission:

- `POST /documents/{document_id}/validate`

Mutation APIs enforce the role matrix above.

## Error Policy

- Missing `X-Actor-Id`: `AUTH_REQUIRED`
- Unknown actor: `PERMISSION_DENIED`
- Actor is not a project member: `PERMISSION_DENIED`
- Actor role lacks the required permission: `PERMISSION_DENIED`

All errors use the standard `{ "error": { "code", "message", "details" } }`
response shape.

## Test Plan

- Existing TASK_001/TASK_002 tests continue to pass.
- Missing actor is denied.
- Non-member read and mutation are denied.
- Viewer can read but cannot patch or validate.
- Reviewer can read, diff, and validate but cannot patch.
- Editor can patch, rollback, and validate but cannot create schema.
- Admin can create schema.
- Permission-denied mutation creates no event and does not alter snapshot.
- Migration creates `project_members` and backfills workspace owner membership.
- Replay consistency remains valid after RBAC-authorized mutation sequences.
