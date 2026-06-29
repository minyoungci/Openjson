# TASK_009 Plan: Deployment Hardening Baseline

TASK_009 adds a minimal deployment hardening baseline for the current backend
MVP.

This task does not add full authentication, password login, token issuance,
enterprise SSO, billing, UI work, realtime collaboration, WebSocket, Git
integration, branching, pull requests, AI features, offline sync, PostgreSQL
migration, Kubernetes, webhook delivery, audit export, automatic
merge/conflict resolution, or complex path-level permissions.

## Scope

- Add public health and readiness endpoints.
- Add an explicit DB initialization command for local/staging smoke setup.
- Add Docker runtime files for the FastAPI backend.
- Add minimal CORS configuration through an environment variable.
- Document deployment/smoke-test boundaries.
- Preserve all document event and replay invariants.

## API Endpoints

- `GET /health`
- `GET /ready`

These endpoints do not require `X-Actor-Id` because they are intended for load
balancers and deployment smoke checks.

## Environment Variables

- `OPENJSON_DB_PATH`: SQLite database path for the current MVP.
- `OPENJSON_CORS_ORIGINS`: comma-separated allowed origins. Empty means CORS
  middleware is not enabled.

## Acceptance Gate

- `python -m unittest discover -v` passes.
- `python -m compileall app tests scripts` passes.
- DB init command is idempotent.
- Health/readiness endpoints return standard payloads.
- Readiness failure uses the standard error envelope.
- No forbidden product scope is implemented.

## Limitations

- SQLite remains local/staging MVP storage, not production-ready storage.
- Production authentication remains an open issue.
- PostgreSQL migration remains a separate task.
- Structured request logging and backup/restore remain separate operational
  hardening tasks.
