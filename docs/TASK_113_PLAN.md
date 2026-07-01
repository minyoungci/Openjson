# TASK_113 Plan: Deploy Auth Fallback Gate

## Objective

Make the production deployment authentication boundary match the user-facing
browser app: users authenticate with session bearer tokens, not with
client-supplied actor ids.

The existing `X-Actor-Id` HTTP header and WebSocket `actor_id` query fallback
remain available by default for local development, legacy tests, and smoke
scripts. Deployments can disable that fallback with:

```text
OPENJSON_ALLOW_ACTOR_HEADER=0
```

## Scope

- Add an auth middleware setting that rejects client-supplied `X-Actor-Id`
  when no bearer token authenticated the request.
- Keep bearer session tokens and project API tokens working; the middleware may
  still derive the internal actor header from a validated bearer token.
- Apply the same setting to WebSocket collaboration connections so tokenless
  `actor_id` query fallback is rejected in deployment mode.
- Configure Render with `OPENJSON_ALLOW_ACTOR_HEADER=0`.
- Document the local/deployment distinction.

## Out of Scope

- Removing `X-Actor-Id` support from local API tests.
- Enterprise auth policy, SAML/SCIM, billing, path-level permissions, Git
  integration, branching, pull requests, or AI features.
- Changing document event persistence, replay, diff, rollback, or validation
  semantics.

## Data Model

No schema change.

## API

No endpoint shape change. Error responses still use the standard envelope.

When the fallback is disabled and a protected HTTP request relies only on
`X-Actor-Id`, the API returns `AUTH_REQUIRED`.

When the fallback is disabled and a WebSocket request supplies only
`actor_id`, the socket is closed with a structured `AUTH_REQUIRED` error.

## Test Plan

- HTTP public endpoints continue to work when the fallback is disabled.
- HTTP `X-Actor-Id`-only protected requests fail with `AUTH_REQUIRED` when the
  fallback is disabled.
- HTTP bearer session requests still work when the fallback is disabled.
- HTTP bearer requests with mismatched `X-Actor-Id` still fail.
- WebSocket tokenless `actor_id` fallback fails when disabled.
- WebSocket session token auth still works when disabled.
