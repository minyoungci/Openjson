# TASK_130_PLAN.md

## Goal

Harden unexpected internal error responses for public deployments.

Structured `AppError` responses intentionally expose known diagnostic fields
for malformed persisted JSON, migration drift, validation failures, and other
expected failure states. Unknown exceptions are different: their raw exception
messages can contain local paths, database paths, provider messages, tokens, or
other sensitive operational context.

## Scope

- Keep the standard error envelope:

```json
{
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "Unexpected internal error.",
    "details": {}
  }
}
```

- For catch-all unknown exceptions, return only:
  - `details.diagnostic_code = "UNEXPECTED_EXCEPTION"`
  - `details.request_id`
- Preserve `X-Request-Id` response headers.
- Store the generated request id on `request.state` so the exception handler can
  include it.
- Add `OPENJSON_DEBUG_ERROR_DETAILS=1` as a local development escape hatch that
  includes `details.error_type` and `details.message`.
- Expose `runtime_config.debug_error_details_enabled` from `GET /version` so
  deployments can verify that debug details are disabled.

## Exclusions

- Do not sanitize or rewrite intentional `AppError` diagnostic payloads.
- Do not add a database table.
- Do not introduce an external logging or error tracking provider.
- Do not change document-event, replay, backup, or migration behavior.

## Verification

```powershell
python -m unittest tests.test_deployment_hardening
python -m compileall app scripts
python -m unittest discover -s tests
python scripts\release_preflight.py
```
