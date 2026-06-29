# TASK_012 Plan: Minimal Project API Token Auth Boundary

TASK_012 adds a minimal project-scoped API token boundary.

This task does not add password login, session cookies, refresh tokens,
enterprise SSO, invitation email flow, billing, UI work, realtime
collaboration, WebSocket, Git integration, branching, pull requests, AI
features, offline sync, PostgreSQL migration, Kubernetes, webhook delivery,
audit export, automatic merge/conflict resolution, or complex path-level
permissions.

## Scope

- Add `api_tokens` table with hashed token storage.
- Add project-scoped API token create/list/revoke endpoints.
- Accept `Authorization: Bearer <token>` as an alternative to `X-Actor-Id`.
- Keep `X-Actor-Id` for local bootstrap/development compatibility.
- Enforce project scope for bearer-token requests.
- Record token create/revoke in `audit_log`.

## API Endpoints

- `POST /projects/{project_id}/api-tokens`
- `GET /projects/{project_id}/api-tokens`
- `DELETE /projects/{project_id}/api-tokens/{token_id}`

## Token Policy

- Token secrets are returned only once on creation.
- Only token hashes are stored.
- Tokens are scoped to one project.
- Project-scoped tokens cannot access workspace bootstrap endpoints.
- A token acts as its owning user and still goes through project RBAC.
- Revoked tokens are rejected.

## Integrity Policy

- Token creation/revocation does not create `document_events`.
- Token creation/revocation does not mutate JSON document snapshots.
- Project token audit events must not include the token secret.
- The replay invariant remains unchanged.

## Acceptance Gate

- `python -m unittest discover -v` passes.
- `python -m compileall app tests scripts` passes.
- Token secret is not stored in plaintext.
- Bearer token access works without `X-Actor-Id`.
- Project scope is enforced.
- Revoked/invalid tokens are rejected with the standard error envelope.
- Existing `X-Actor-Id` tests continue to pass.

## Limitations

- This is not a password login system.
- This is not a session or refresh-token system.
- Token expiry, rotation, rate limiting, and admin-wide token management remain
  future hardening tasks.
