# TASK_117 Plan: WebSocket Message Rate Limit Guard

## Objective

Add a basic per-connection WebSocket message limit so realtime collaboration
channels cannot be spammed without bound on the public single-instance
deployment.

HTTP rate limiting does not apply to already-upgraded WebSocket connections, so
this task adds a separate in-memory guard around incoming collaboration
messages.

## Scope

- Add a per-WebSocket-connection fixed-window message limiter.
- Configure it with `OPENJSON_WS_RATE_LIMIT_*` environment variables.
- Return a structured WebSocket `RATE_LIMITED` error payload and close the
  connection with policy-violation code `1008`.
- Expose non-secret WebSocket rate-limit flags from `GET /version`.
- Enable conservative defaults in `render.yaml`.
- Keep `/health`, `/ready`, document events, snapshots, audit rows, and
  collaboration persistence semantics unchanged.

## Out of Scope

- Distributed or Redis-backed WebSocket rate limiting.
- Cloudflare WAF/rules automation.
- Per-project quotas or billing.
- WebSocket connection count limits.
- Persistent rate-limit audit tables.
- Changing text collaboration merge, commit, or canonical persistence behavior.

## Data Model

No schema change. The limiter is in-memory per connection and does not mutate
canonical JSON documents, `document_events`, `audit_log`, `editor_presence`, or
text collaboration session state.

## Environment Variables

```text
OPENJSON_WS_RATE_LIMIT_ENABLED=1
OPENJSON_WS_RATE_LIMIT_MESSAGES=120
OPENJSON_WS_RATE_LIMIT_WINDOW_SECONDS=60
```

When disabled or unset, WebSocket message limiting is not installed.

## WebSocket Error

Limited connections receive:

```json
{
  "type": "error",
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many WebSocket messages. Please retry after the rate limit window resets.",
    "details": {
      "limit": 120,
      "window_seconds": 60,
      "retry_after_seconds": 42
    }
  }
}
```

The server sends the error and then closes the connection.

## Test Plan

- WebSocket messages are accepted up to the configured per-window limit.
- The next message receives `RATE_LIMITED` and the socket closes.
- Existing presence, refresh, and text-session behavior remains unchanged.
- `/version` exposes non-secret WebSocket rate-limit runtime config.
- Render config includes the WebSocket rate-limit env vars.
