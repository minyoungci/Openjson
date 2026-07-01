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
enabled on the checked connection, required tables exist, and the schema
migration ledger is current.

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
- `OPENJSON_RATE_LIMIT_ENABLED`: set to `1`, `true`, or `yes` to enable the
  in-process HTTP rate limit.
- `OPENJSON_RATE_LIMIT_REQUESTS`: request count per fixed window. Defaults to
  `120`.
- `OPENJSON_RATE_LIMIT_WINDOW_SECONDS`: fixed window size in seconds. Defaults
  to `60`.
- `OPENJSON_WS_RATE_LIMIT_ENABLED`: set to `1`, `true`, or `yes` to enable the
  in-process per-connection WebSocket message limit.
- `OPENJSON_WS_RATE_LIMIT_MESSAGES`: message count per fixed window. Defaults
  to `120`.
- `OPENJSON_WS_RATE_LIMIT_WINDOW_SECONDS`: fixed window size in seconds.
  Defaults to `60`.
- `OPENJSON_REQUEST_BODY_LIMIT_ENABLED`: set to `1`, `true`, or `yes` to
  reject oversized HTTP request bodies before endpoint parsing.
- `OPENJSON_MAX_REQUEST_BODY_BYTES`: maximum accepted HTTP request body size.
  Defaults to `10485760`.
- `OPENJSON_PROJECT_USAGE_LIMIT_ENABLED`: set to `1`, `true`, or `yes` to
  enforce project active document and active snapshot-byte limits.
- `OPENJSON_MAX_PROJECT_DOCUMENTS`: maximum active documents per project.
  Defaults to `10000`.
- `OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES`: maximum active latest snapshot bytes
  per project. Defaults to `104857600`.

Example:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
$env:OPENJSON_CORS_ORIGINS = "http://localhost:3000"
$env:OPENJSON_RATE_LIMIT_ENABLED = "1"
$env:OPENJSON_WS_RATE_LIMIT_ENABLED = "1"
$env:OPENJSON_REQUEST_BODY_LIMIT_ENABLED = "1"
$env:OPENJSON_PROJECT_USAGE_LIMIT_ENABLED = "1"
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
  refresh tokens, SSO, token expiry, or distributed/plan-based rate limiting.
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
- `scripts/backup_restore_drill.py`

Restore verifies adjacent backup manifest hashes when a manifest is present.
Malformed manifests fail before target DB creation; missing manifests are
reported and allowed for backward compatibility.

The backup restore drill creates a backup, restores it into a temporary
database, and requires the restored database combined integrity check to pass
before the drill is considered successful.

`scripts/release_preflight.py` treats these operational scripts as required
release files, so a deployment preflight fails before deploy if the backup,
restore, integrity, encryption helper, or restore-drill script is missing. See
`docs/TASK_126_PLAN.md`.

SQLite backup retention is optional through `--retention-count` or
`OPENJSON_BACKUP_RETENTION_COUNT`. It prunes only older
`openjson-backup-*.sqlite3` files and adjacent manifests after a newly created
backup passes the combined integrity check.

See `docs/OPERATIONS_BASELINE.md`.
