# TASK_118 Plan: HTTP Request Body Size Guard

## Objective

Add a deployment-safe request body size guard before public use of ZIP import
and raw JSON save APIs.

The goal is not billing, storage quotas, or a plan-based usage system. The goal
is to prevent oversized HTTP request bodies from being accepted into the app
process without a clear standard error response.

## Scope

- Add an app-level HTTP request body limit middleware.
- Configure it with deployment environment variables.
- Return the standard error envelope with HTTP 413.
- Expose non-secret body limit runtime flags from `GET /version`.
- Enable a conservative default limit in `render.yaml`.
- Add regression coverage for body-limit rejection before mutation.

## Environment

```text
OPENJSON_REQUEST_BODY_LIMIT_ENABLED=1
OPENJSON_MAX_REQUEST_BODY_BYTES=10485760
```

The default max value is 10 MiB, matching the current ZIP archive limit.

## Error Contract

Oversized requests return:

```json
{
  "error": {
    "code": "REQUEST_BODY_TOO_LARGE",
    "message": "Request body exceeds the configured size limit.",
    "details": {
      "request_bytes": 10485761,
      "max_request_body_bytes": 10485760
    }
  }
}
```

## Excluded

- Per-user or per-project storage quotas.
- Billing or paid usage enforcement.
- Cloudflare WAF/ruleset automation.
- Background upload jobs.
- Direct-to-object-storage uploads.
- Changing ZIP import's existing all-or-nothing document event behavior.
- Changing canonical document storage or event replay semantics.

## Verification

- Oversized HTTP mutation requests receive `REQUEST_BODY_TOO_LARGE` with 413.
- Rejected oversized requests do not create document or event rows.
- `/version` exposes non-secret body-limit runtime config.
- `render.yaml` includes body-limit env vars.
