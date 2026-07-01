# TASK_129_PLAN.md

## Goal

Add a read-only backup status check for the SQLite MVP deployment.

The backup scheduler can create encrypted integrity-checked backups, but
operators also need a small command that can be run from Render shell, CI, or a
monitoring wrapper to verify that the latest backup is recent, intact, and
optionally encrypted.

## Scope

- Add `scripts/check_backup_status.py`.
- Inspect the latest `openjson-backup-*.manifest.json` file in the configured
  backup output directory.
- Verify:
  - a manifest exists
  - the manifest is valid JSON
  - the referenced backup file exists
  - backup size matches the manifest
  - backup SHA-256 matches the manifest
  - manifest `integrity.status` is `ok`
  - backup age is within `--max-age-seconds`
  - encryption is present when `--require-encrypted` or
    `OPENJSON_BACKUP_ENCRYPT=1` is used
- Return structured JSON and exit nonzero when any check fails.
- Register the script as a required operation file in release preflight.

## Command

```powershell
python scripts\check_backup_status.py `
  --output-dir "D:\OpenJson\backups" `
  --max-age-seconds 90000 `
  --require-encrypted
```

Environment defaults:

```text
OPENJSON_BACKUP_OUTPUT_DIR
OPENJSON_BACKUP_MAX_AGE_SECONDS
OPENJSON_BACKUP_ENCRYPT
```

## Render Example

```bash
python scripts/check_backup_status.py \
  --output-dir /data/backups \
  --max-age-seconds 90000 \
  --require-encrypted
```

## Exclusions

- No database schema change.
- No backup file mutation.
- No restore operation.
- No alerting provider integration.
- No remote object storage lifecycle management.
- No PostgreSQL backup status checks.
