# TASK_007 Hardening

This document records the TASK_007 project membership hardening policy.

TASK_007_HARDENING does not add full authentication, password login, token
issuance, invitation flow, email delivery, workspace role tables, billing, UI
work, realtime collaboration, WebSocket, Git integration, branching, pull
requests, AI features, offline sync, automatic merge/conflict resolution, or
complex path-level permissions.

## Scope

- Enforce last-owner protection at the SQLite trigger level.
- Verify that removed members immediately lose project, document, comment,
  schema, review, and membership access.
- Verify that role changes immediately affect permission checks.
- Verify HTTP edge cases for malformed membership requests and missing members.
- Preserve the rule that membership changes do not create `document_events`.

## DB-Level Owner Protection

The service already rejects removing or demoting the last project owner.

Hardening adds SQLite triggers so direct SQL update/delete attempts also cannot
leave a project without an owner:

- `trg_project_members_keep_owner_update`
- `trg_project_members_keep_owner_delete`

## Access Revocation Policy

After a member is removed from a project, subsequent calls requiring project
membership must return `PERMISSION_DENIED`.

This includes project detail, member list, document read, document history,
comments, schemas, and reviews.

## Role Change Policy

Role changes take effect immediately. For example, changing an editor to a
viewer removes document write permission while preserving document read
permission.

## Tests

Hardening tests cover:

- direct SQL demotion/deletion of last owner is rejected
- migration creates owner-protection triggers idempotently
- removed members lose project-scoped access
- role changes immediately affect document write permission
- HTTP malformed membership payload uses the standard error envelope
- HTTP missing member update/delete returns `PROJECT_MEMBER_NOT_FOUND`
