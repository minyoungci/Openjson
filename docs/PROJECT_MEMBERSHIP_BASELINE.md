# Project Membership Baseline

This document records the TASK_007 minimal project membership management
baseline.

TASK_007 manages project-level roles for existing users only. It does not add
full authentication, password login, token issuance, invitation flow, email
delivery, workspace role tables, billing, UI work, realtime collaboration,
WebSocket, Git integration, branching, pull requests, AI features, offline sync,
automatic merge/conflict resolution, or complex path-level permissions.

## API

- `GET /projects/{project_id}/members`
- `POST /projects/{project_id}/members`
- `PATCH /projects/{project_id}/members/{user_id}`
- `DELETE /projects/{project_id}/members/{user_id}`

All endpoints require `X-Actor-Id`.

## Roles

- `owner`
- `admin`
- `editor`
- `reviewer`
- `viewer`

## Permission Policy

- Any project member can list project members.
- `owner` and `admin` can add, update, or remove project members.
- `editor`, `reviewer`, and `viewer` cannot manage members.
- Non-members cannot list or manage members.

## Owner Protection

Every project must retain at least one owner.

The service rejects:

- removing the last owner
- changing the last owner to any non-owner role

TASK_007_HARDENING also enforces this invariant with DB triggers:

- `trg_project_members_keep_owner_update`
- `trg_project_members_keep_owner_delete`

## Data Model

Membership remains stored in `project_members`.

No invitation table, workspace membership table, or path-level permission table
is added in TASK_007.

## Integrity

Membership changes do not mutate JSON documents and do not create
`document_events`.

TASK_008 records successful and rejected membership management attempts in the
separate append-only `audit_log` table.

Removed members immediately lose project-scoped access. Role updates immediately
change project-scoped permissions.

The document replay invariant remains:

```text
Replay(DocumentEvent[0..N]) == json_documents.current_snapshot_json
```

See `docs/TASK_007_HARDENING.md` for the hardening policy.
