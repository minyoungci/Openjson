# Operations Baseline

This document records the TASK_010 observability, replay check, and backup
baseline.

The current backend is still a local/staging MVP. This document does not define
a production SRE program, managed database backup policy, centralized logging
stack, metrics pipeline, alerting policy, or disaster recovery SLA.

TASK_010 does not add full authentication, password login, token issuance,
enterprise SSO, billing, UI work, realtime collaboration, WebSocket, Git
integration, branching, pull requests, AI features, offline sync, PostgreSQL
migration, Kubernetes, webhook delivery, audit export, automatic
merge/conflict resolution, or complex path-level permissions.

## Request Observability

Every HTTP response receives an `X-Request-Id` header.

If the request includes `X-Request-Id`, the server preserves it. Otherwise the
server generates a `req_...` id.

Structured request logging is opt-in:

```powershell
$env:OPENJSON_REQUEST_LOGGING = "1"
```

When enabled, each request emits a JSON line to stdout with:

- `event`
- `request_id`
- `method`
- `path`
- `status_code`
- `duration_ms`
- `actor_id`

## Replay Consistency Check

Before replay/backup smoke checks, the local/staging database should be at the
current migration baseline:

```powershell
python scripts\migrate_db.py
```

Run:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\check_replay_consistency.py
```

The command checks every row in `json_documents`:

- `current_version` equals the latest `document_events.result_version`
- replaying `document_events` reconstructs `current_snapshot_json`
- malformed persisted snapshot or event JSON is reported as structured
  integrity failure

It exits with code `1` if any document fails the invariant.

## Event Chain Integrity Check

Run:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\check_event_chain_integrity.py
```

The command checks every row in `json_documents`:

- event versions form a contiguous `base_version -> result_version` chain
- event types are supported document mutation events
- stored `changed_paths`, `inverse_patch`, `before_values`, and `after_values`
  match replay-observed metadata
- replaying the event chain reconstructs `current_snapshot_json`
- malformed persisted snapshot or event JSON is reported as structured
  integrity failure

It exits with code `1` if any document has a broken event chain.

## Combined Database Integrity Check

Run:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\check_database_integrity.py
```

The command runs replay consistency, event-chain metadata integrity, SQLite
foreign key integrity, SQLite structural integrity, and migration ledger
integrity checks in one read-only report. It exits with code `1` if any check
fails.

SQLite-level checks:

- `PRAGMA foreign_key_check`
- `PRAGMA integrity_check`

Migration-level checks:

- `schema_migrations` contains every known migration baseline id
- `schema_migrations` contains no unknown migration ids

## SQLite MVP Backup

Create a backup:

```powershell
python scripts\backup_sqlite.py --db-path "D:\OpenJson\openjson.sqlite3" --output-dir "D:\OpenJson\backups"
```

The command writes:

- a SQLite backup file
- a JSON manifest containing size, SHA-256, timestamp, and a combined integrity
  envelope with replay consistency, event-chain metadata, SQLite integrity, and
  migration ledger checks

The backup command does not initialize or migrate the source database. The
source database must already exist.

Optional retention:

```powershell
python scripts\backup_sqlite.py --db-path "D:\OpenJson\openjson.sqlite3" --output-dir "D:\OpenJson\backups" --retention-count 7
```

`OPENJSON_BACKUP_RETENTION_COUNT` may be used as the default retention count.
Retention applies only to `openjson-backup-*.sqlite3` files in the selected
output directory, including encrypted `openjson-backup-*.sqlite3.enc` files,
and deletes adjacent manifest files for pruned backups. It runs only when the
newly created backup's combined integrity status is `ok`; failed-integrity
backups skip pruning so older known backups remain available.

Optional encryption:

```powershell
python scripts\backup_sqlite.py --generate-encryption-key
$env:OPENJSON_BACKUP_ENCRYPTION_KEY = "<generated-key>"
python scripts\backup_sqlite.py `
  --db-path "D:\OpenJson\openjson.sqlite3" `
  --output-dir "D:\OpenJson\backups" `
  --encrypt `
  --retention-count 7
```

Encrypted backup files use `.sqlite3.enc`. The manifest records ciphertext
size/SHA-256 and plaintext size/SHA-256, but it never stores the encryption
key. The temporary plaintext backup is deleted after encryption.

## SQLite MVP Restore

Restore a backup:

```powershell
python scripts\restore_sqlite.py --backup-path "D:\OpenJson\backups\openjson-backup.sqlite3" --target-db-path "D:\OpenJson\restored.sqlite3"
```

The restore command refuses to overwrite an existing target unless `--force` is
provided. It validates replay consistency, event-chain metadata integrity,
SQLite integrity, and migration ledger integrity after restore.

When an adjacent `.manifest.json` exists, restore verifies the backup file hash
and size before writing the target DB. Malformed manifest JSON fails before
target creation. Missing manifests are reported as `not_found` and restore
continues for backward compatibility.

Restore an encrypted backup:

```powershell
$env:OPENJSON_BACKUP_ENCRYPTION_KEY = "<generated-key>"
python scripts\restore_sqlite.py `
  --backup-path "D:\OpenJson\backups\openjson-backup-<timestamp>.sqlite3.enc" `
  --target-db-path "D:\OpenJson\restored.sqlite3"
```

Encrypted restore verifies the ciphertext manifest, decrypts to a temporary
SQLite file, verifies plaintext size/SHA-256, restores the target DB, then
runs the same combined integrity checks. Missing or wrong encryption keys fail
before target creation.

## SQLite Backup Restore Drill

Run a full backup and restore drill:

```powershell
$env:OPENJSON_BACKUP_ENCRYPTION_KEY = "<generated-key>"
python scripts\backup_restore_drill.py `
  --db-path "D:\OpenJson\openjson.sqlite3" `
  --output-dir "D:\OpenJson\backups" `
  --encrypt `
  --retention-count 7 `
  --report-path "D:\OpenJson\backups\latest-drill-report.json"
```

The drill exits successfully only when backup integrity and restored database
integrity are both `ok`. It deletes the temporary restored database by default.

## SQLite Backup Status Check

Check the latest backup manifest without creating, restoring, or deleting
backup files:

```powershell
python scripts\check_backup_status.py `
  --output-dir "D:\OpenJson\backups" `
  --max-age-seconds 90000
```

For encrypted scheduled backups, require encryption in the latest manifest:

```powershell
python scripts\check_backup_status.py `
  --output-dir "D:\OpenJson\backups" `
  --max-age-seconds 90000 `
  --require-encrypted
```

The command exits nonzero if the latest manifest is missing or malformed, the
referenced backup file is missing, file size or SHA-256 does not match the
manifest, `integrity.status` is not `ok`, the backup is too old, or encryption
is required but absent. See `docs/TASK_129_PLAN.md`.

## SQLite Backup Scheduler

For the current single-instance SQLite deployment, the FastAPI app can run a
daily backup loop inside the web service process:

```powershell
$env:OPENJSON_BACKUP_SCHEDULER_ENABLED = "1"
$env:OPENJSON_BACKUP_OUTPUT_DIR = "D:\OpenJson\backups"
$env:OPENJSON_BACKUP_INTERVAL_SECONDS = "86400"
$env:OPENJSON_BACKUP_RETENTION_COUNT = "7"
$env:OPENJSON_BACKUP_ENCRYPT = "1"
$env:OPENJSON_BACKUP_ENCRYPTION_KEY = "<generated-key>"
```

The scheduler reuses `scripts\backup_sqlite.py`. It logs structured
`sqlite_backup_scheduler` events for started, completed, and failed backup
attempts. A failed scheduled backup does not stop the web service.

Render cron jobs cannot access a web service persistent disk, so the Render
SQLite baseline intentionally uses this in-process scheduler instead of a
separate cron service.

## Boundaries

- Backup scheduling is implemented only for the current single-instance SQLite
  deployment as an in-process web service task.
- Backup retention is local filesystem retention only; there is no managed
  remote object storage lifecycle policy.
- Backup status checks are read-only filesystem checks over the latest
  manifest and backup file; they do not replace offsite backup monitoring.
- Backup encryption is implemented for the SQLite MVP script, but key
  management and rotation remain external operational responsibilities.
- PostgreSQL backup/restore is a future task.
- Centralized logs, metrics, traces, and alerting are future tasks.
- Replay consistency checks are read-only and do not repair corrupted data.
- Event-chain integrity checks are read-only and do not repair corrupted data.
- Combined database integrity checks are read-only and do not repair corrupted
  data.
- Backup and restore integrity status is `ok` only when replay, event-chain,
  SQLite integrity, and migration ledger checks pass.
