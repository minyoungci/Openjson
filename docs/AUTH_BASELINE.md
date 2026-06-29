# Auth Baseline

This document records the TASK_012 minimal project API token boundary.

The current service still does not implement password login, session cookies,
refresh tokens, enterprise SSO, invitation email flow, billing, UI work,
realtime collaboration, WebSocket, Git integration, branching, pull requests,
AI features, offline sync, PostgreSQL migration, Kubernetes, webhook delivery,
audit export, automatic merge/conflict resolution, or complex path-level
permissions.

## Local Actor Boundary

For local development and bootstrap flows, `X-Actor-Id` remains supported:

```text
X-Actor-Id: user_...
```

`POST /users`, `GET /health`, and `GET /ready` remain public.

## API Token Boundary

Project-scoped API tokens can be used as:

```text
Authorization: Bearer <token>
```

Token management endpoints:

- `POST /projects/{project_id}/api-tokens`
- `GET /projects/{project_id}/api-tokens`
- `DELETE /projects/{project_id}/api-tokens/{token_id}`

All token management requests require either `X-Actor-Id` or a valid bearer
token.

## Token Storage

Token secrets are returned only once, on creation.

The database stores:

- token id
- owning user id
- project id
- display name
- short token prefix
- SHA-256 token hash
- created timestamp
- last-used timestamp
- revoked timestamp

The raw token secret is never stored.

## Scope Policy

- Tokens are scoped to exactly one project.
- Tokens act as their owning user.
- Project RBAC is still enforced.
- Document mutations performed with a token create normal `document_events`
  attributed to the token owner.
- Tokens cannot access workspace bootstrap endpoints.
- Tokens cannot access another project.
- Schema endpoints are also scoped through the schema's owning project.
- Revoked tokens are rejected with `AUTH_REQUIRED`.

## Audit Policy

Token creation and revocation create `audit_log` rows:

- `api_token.create`
- `api_token.revoke`

Audit details include token id and prefix, not the token secret.

Token management does not create `document_events` and does not mutate document
snapshots.

If the success audit write for token creation or revocation fails, the token
mutation is rolled back and the rejected attempt is recorded as a failure audit
row. See `docs/TASK_053_PLAN.md`.

Schema resource scope edge cases are pinned in `docs/TASK_054_PLAN.md`.

Document mutation actor attribution through bearer tokens is pinned in
`docs/TASK_055_PLAN.md`.

Bearer-token restore and rollback actor attribution is pinned in
`docs/TASK_056_PLAN.md`.

Bearer-token replay-dependent read surfaces are pinned in
`docs/TASK_057_PLAN.md`.

Bearer-token path history and blame read surfaces are pinned in
`docs/TASK_058_PLAN.md`.

Bearer-token schema validation mutation atomicity is pinned in
`docs/TASK_059_PLAN.md`.

Bearer-token schema validation restore and rollback atomicity is pinned in
`docs/TASK_060_PLAN.md`.

Bearer-token document validate read behavior is pinned in
`docs/TASK_061_PLAN.md`.

Bearer-token document patch preview scope is pinned in
`docs/TASK_080_PLAN.md`.

## Limitations

- No password login.
- No refresh token flow.
- No token expiry yet.
- No rate limiting yet.
- No admin-wide token management yet.
- No token rotation endpoint yet.
