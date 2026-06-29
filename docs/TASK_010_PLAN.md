# TASK_010 Plan: Observability, Replay Check, Backup Baseline

TASK_010 adds a minimal operational baseline for the current backend MVP.

This task does not add full authentication, password login, token issuance,
enterprise SSO, billing, UI work, realtime collaboration, WebSocket, Git
integration, branching, pull requests, AI features, offline sync, PostgreSQL
migration, Kubernetes, webhook delivery, audit export, automatic
merge/conflict resolution, or complex path-level permissions.

## Scope

- Add request ID propagation for HTTP responses.
- Add optional structured JSON request logging.
- Add a replay consistency checker for all JSON documents.
- Add SQLite MVP backup and restore smoke scripts.
- Document the operational boundary for local/staging use.

## Environment Variables

- `OPENJSON_REQUEST_LOGGING`: set to `1`, `true`, or `yes` to emit structured
  request logs to stdout.

Request logging is opt-in for the local test environment to keep test output
quiet. Request ID response headers are always added.

## Scripts

- `scripts/check_replay_consistency.py`
- `scripts/backup_sqlite.py`
- `scripts/restore_sqlite.py`

## Integrity Policy

- Replay checks are read-only.
- Backup and restore scripts must not mutate source databases.
- Restore validates replay consistency after writing the restored database.
- SQLite backup/restore is an MVP smoke baseline, not a production backup
  policy.

## Acceptance Gate

- `python -m unittest discover -v` passes.
- `python -m compileall app tests scripts` passes.
- Request ID propagation is tested.
- Structured request log shape is tested.
- Replay consistency success and failure are tested.
- Backup and restore smoke path is tested.
- No forbidden product scope is implemented.

## Limitations

- Logs are stdout JSON lines, not a centralized logging stack.
- Metrics, tracing, alerting, backup encryption, retention, and scheduled jobs
  remain future operational tasks.
- PostgreSQL backup/restore remains part of the future PostgreSQL migration.
