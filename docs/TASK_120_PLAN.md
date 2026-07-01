# TASK_120 Plan: SQLite Backup Retention Guard

## Objective

Add a small operational retention guard to the existing SQLite MVP backup
script so local/staging deployments can avoid unbounded backup file growth.

This is not a managed disaster-recovery system. It is a conservative file
cleanup option around the existing integrity-checked SQLite backup flow.

## Scope

- Add optional backup retention to `scripts/backup_sqlite.py`.
- Keep only the latest N OpenJson SQLite backup files in the output directory.
- Delete each pruned backup's adjacent `.manifest.json` when present.
- Skip pruning when the newly created backup fails combined database integrity.
- Expose the option through `--retention-count` and
  `OPENJSON_BACKUP_RETENTION_COUNT`.
- Document the local/staging usage and boundaries.
- Add regression coverage for successful pruning and integrity-failure skip.

## Command

```powershell
python scripts\backup_sqlite.py `
  --db-path "D:\OpenJson\openjson.sqlite3" `
  --output-dir "D:\OpenJson\backups" `
  --retention-count 7
```

Equivalent environment default:

```powershell
$env:OPENJSON_BACKUP_RETENTION_COUNT = "7"
python scripts\backup_sqlite.py --db-path "D:\OpenJson\openjson.sqlite3" --output-dir "D:\OpenJson\backups"
```

## Retention Policy

- Retention applies only to files matching `openjson-backup-*.sqlite3` in the
  chosen output directory.
- The newly created backup is protected from pruning.
- The source database path is protected if it happens to live in the output
  directory.
- Pruning runs only after the newly created backup's combined integrity status
  is `ok`.
- If integrity fails, the new backup and older backups remain in place for
  investigation and rollback safety.

## Manifest

The backup manifest includes a `retention` section:

```json
{
  "retention": {
    "status": "ok",
    "keep_count": 7,
    "pruned_count": 1,
    "remaining_count": 7,
    "pruned": []
  }
}
```

When no retention is requested:

```json
{
  "retention": {
    "enabled": false
  }
}
```

When integrity fails:

```json
{
  "retention": {
    "enabled": true,
    "status": "skipped",
    "keep_count": 7,
    "reason": "integrity_failed"
  }
}
```

## Data Model

No database schema changes.

Backup retention is filesystem operational state only. It does not mutate
`json_documents`, `document_events`, migrations, audit rows, or canonical JSON
content.

## Excluded

- Backup encryption.
- Remote object storage.
- Backup scheduler or cron management.
- PostgreSQL backup/restore.
- Point-in-time recovery.
- Disaster recovery SLA.
