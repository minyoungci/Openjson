# TASK_116 Plan: HTTP Rate Limit Guard

## Objective

Add a simple application-level HTTP rate limit so the public deployment has a
basic usage guard before wider sharing.

The current Render setup is single-instance and cost-controlled, but public
links can still receive accidental or abusive request bursts. This task adds a
small in-memory fixed-window limiter controlled by environment variables and
enabled in `render.yaml`.

## Scope

- Add HTTP rate limiting middleware.
- Return standard error envelope code `RATE_LIMITED` with HTTP 429.
- Emit `X-RateLimit-*` and `Retry-After` headers.
- Exempt `OPTIONS`, `/health`, and `/ready` so deploy health checks keep
  working.
- Key limits by bearer token hash when present, then `X-Actor-Id`, then
  forwarded/client IP.
- Expose non-secret rate-limit runtime flags from `GET /version`.
- Enable conservative default limits in Render config.

## Out of Scope

- Distributed or Redis-backed rate limiting.
- Cloudflare WAF/rules automation.
- Per-project billing quotas.
- WebSocket message rate limiting.
- Persistent rate-limit audit tables.
- Complex plan-based quota management.

## Data Model

No schema change. The limiter is in-memory process state and does not mutate
canonical JSON document data, `document_events`, `audit_log`, or auth tables.

## Environment Variables

```text
OPENJSON_RATE_LIMIT_ENABLED=1
OPENJSON_RATE_LIMIT_REQUESTS=120
OPENJSON_RATE_LIMIT_WINDOW_SECONDS=60
```

When disabled or unset, no HTTP rate limit middleware is installed.

## API

Limited responses use:

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests. Please retry after the rate limit window resets.",
    "details": {
      "limit": 120,
      "window_seconds": 60,
      "retry_after_seconds": 42
    }
  }
}
```

## Test Plan

- Enabled limiter returns 429 after the configured request count.
- 429 uses the standard error envelope and rate-limit headers.
- `/health` and `/ready` remain exempt.
- `/version` exposes non-secret rate-limit runtime config.
- Render config includes the rate-limit env vars.
