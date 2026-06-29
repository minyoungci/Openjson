# Deployment Baseline

This document records the TASK_009 minimal deployment hardening baseline.

The current backend is still a local/staging MVP. SQLite is not treated as
production-ready storage. PostgreSQL migration, full production authentication,
centralized observability, backup/restore automation, and real deployment
pipelines remain separate tasks.

TASK_009 does not add full authentication, password login, token issuance,
enterprise SSO, billing, UI work, realtime collaboration, WebSocket, Git
integration, branching, pull requests, AI features, offline sync, Kubernetes,
webhook delivery, audit export, automatic merge/conflict resolution, or complex
path-level permissions.

## Health and Readiness

- `GET /health`
- `GET /ready`

These endpoints are public and do not require `X-Actor-Id`.

`/health` confirms the API process is running.

`/ready` confirms the configured SQLite database is reachable, foreign keys are
enabled on the checked connection, and required tables exist.

Readiness failures use the standard error envelope with `INTERNAL_ERROR` and
HTTP 503.

## DB Initialization

Initialize or migrate the current SQLite schema explicitly:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\init_db.py
```

The command is idempotent and prints the initialized table list.

Managed migration smoke:

```powershell
python scripts\migrate_db.py
python scripts\migrate_db.py --status
```

See `docs/MIGRATIONS_BASELINE.md` for the SQLite MVP migration ledger policy.

## Runtime Environment

- `OPENJSON_DB_PATH`: SQLite database path.
- `OPENJSON_CORS_ORIGINS`: comma-separated allowed origins. Empty means CORS
  middleware is not enabled.
- `OPENJSON_REQUEST_LOGGING`: set to `1`, `true`, or `yes` to emit structured
  request logs to stdout.

Example:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
$env:OPENJSON_CORS_ORIGINS = "http://localhost:3000"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Docker Smoke Runtime

Build:

```powershell
docker build -t openjson-api .
```

Run:

```powershell
docker run --rm -p 8000:8000 -v openjson_data:/data openjson-api
```

Then check:

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

## Boundaries

- The Dockerfile is a backend runtime smoke baseline, not a complete production
  deployment architecture.
- The current `X-Actor-Id` header is local development identity only.
- TASK_012 adds project-scoped API tokens, but not password login, sessions,
  refresh tokens, SSO, token expiry, or rate limiting.
- Secrets, managed database credentials, TLS, centralized logging, and error
  tracking are not implemented in this task.
- Document mutation integrity remains enforced by `document_events` and replay
  consistency tests, not by deployment packaging.

## Operational Follow-up

TASK_010 adds the first local/staging operational smoke commands:

- request ID propagation
- optional JSON request logs
- `scripts/check_replay_consistency.py`
- `scripts/backup_sqlite.py`
- `scripts/restore_sqlite.py`

Restore verifies adjacent backup manifest hashes when a manifest is present.
Malformed manifests fail before target DB creation; missing manifests are
reported and allowed for backward compatibility.

See `docs/OPERATIONS_BASELINE.md`.
