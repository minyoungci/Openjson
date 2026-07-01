# TASK_125_PLAN.md

## Goal

Add a one-command SQLite backup restore drill for local/staging production
readiness checks.

This task addresses the technical-spec requirement that restore procedures must
be tested before production launch. It does not add a managed backup service,
automatic daily scheduler, remote object storage, or PostgreSQL backup
implementation.

## Scope

- Add `scripts/backup_restore_drill.py`.
- Create an integrity-checked backup using the existing backup flow.
- Restore the backup into a temporary SQLite database.
- Run the existing combined database integrity check on the restored database.
- Remove the temporary restored database by default.
- Optionally keep the restored database for manual inspection.
- Optionally write a JSON drill report for cron/monitoring handoff.
- Support encrypted backups through the same
  `OPENJSON_BACKUP_ENCRYPTION_KEY` policy as `backup_sqlite.py`.

## Drill Policy

The drill is successful only when:

1. backup creation succeeds;
2. backup integrity is `ok`;
3. restore succeeds;
4. restored database integrity is `ok`.

If backup integrity fails, restore is skipped and the command exits nonzero.

## Commands

Plaintext local/staging drill:

```powershell
python scripts\backup_restore_drill.py `
  --db-path "D:\OpenJson\openjson.sqlite3" `
  --output-dir "D:\OpenJson\backups" `
  --retention-count 7 `
  --report-path "D:\OpenJson\backups\latest-drill-report.json"
```

Encrypted drill:

```powershell
$env:OPENJSON_BACKUP_ENCRYPTION_KEY = "<generated-key>"
python scripts\backup_restore_drill.py `
  --db-path "D:\OpenJson\openjson.sqlite3" `
  --output-dir "D:\OpenJson\backups" `
  --encrypt `
  --retention-count 7 `
  --report-path "D:\OpenJson\backups\latest-drill-report.json"
```

Keep the restored drill database:

```powershell
python scripts\backup_restore_drill.py `
  --db-path "D:\OpenJson\openjson.sqlite3" `
  --output-dir "D:\OpenJson\backups" `
  --restore-dir "D:\OpenJson\restore-drills" `
  --keep-restored
```

## Exclusions

- No automatic daily scheduler.
- No remote object storage upload.
- No PostgreSQL backup/restore implementation.
- No external alerting integration.
- No key-management service integration.
