# TASK_127_PLAN.md

## Goal

Add an opt-in daily SQLite backup scheduler for the single-instance Render
deployment.

The technical specification requires production database backups to run at
least daily. Render cron jobs cannot access a web service's persistent disk, so
the current SQLite MVP uses an in-process scheduler inside the single web
service instance that owns `/data/openjson.sqlite3`.

## Scope

- Add `app/backup_scheduler.py`.
- Reuse the existing integrity-checked `scripts/backup_sqlite.py` flow.
- Run backups in a background task started during FastAPI startup.
- Keep the app alive if a scheduled backup fails; log a structured failure
  event instead.
- Expose non-secret scheduler state in `GET /version`.
- Enable the scheduler in `render.yaml` with encrypted backups, daily interval,
  and retention.
- Keep `OPENJSON_BACKUP_ENCRYPTION_KEY` as a Render secret (`sync: false`).
- Extend release/deployment preflight checks to verify the scheduler guard.

## Environment

```text
OPENJSON_BACKUP_SCHEDULER_ENABLED=1
OPENJSON_BACKUP_OUTPUT_DIR=/data/backups
OPENJSON_BACKUP_INTERVAL_SECONDS=86400
OPENJSON_BACKUP_RETENTION_COUNT=7
OPENJSON_BACKUP_ENCRYPT=1
OPENJSON_BACKUP_ENCRYPTION_KEY=<Render secret>
```

`GET /version` reports only non-secret values:

- `runtime_config.backup_scheduler_enabled`
- `runtime_config.backup_scheduler_interval_seconds`
- `runtime_config.backup_scheduler_retention_count`
- `runtime_config.backup_scheduler_encrypt`
- `runtime_config.backup_encryption_key_configured`

It does not expose the DB path, backup output path, or encryption key.

## Verification

```powershell
python -m unittest tests.test_backup_scheduler tests.test_release_preflight tests.test_deployment_hardening
python -m compileall app scripts
python -m unittest discover -s tests
python scripts\release_preflight.py
```

After Render deploy:

```powershell
python scripts\release_preflight.py `
  --base-url https://openjson.thelumen.work `
  --expect-commit <git-sha> `
  --expect-actor-header-allowed false `
  --expect-backup-scheduler-enabled true
```

## Exclusions

- No Render cron job for SQLite backups because Render cron jobs cannot access
  the web service persistent disk.
- No remote object storage lifecycle management.
- No managed backup provider integration.
- No PostgreSQL backup, point-in-time recovery, or database migration.
- No alerting integration beyond structured stdout logs.
