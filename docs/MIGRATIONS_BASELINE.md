# Migrations Baseline

This document records the TASK_011 managed migration baseline.

The current backend still uses SQLite for local/staging MVP work. This baseline
does not introduce PostgreSQL, Alembic, SQLAlchemy, production migration
pipelines, or managed cloud database operations.

TASK_011 does not add full authentication, password login, enterprise SSO,
billing, UI work, realtime collaboration, WebSocket, Git integration,
branching, pull requests, AI features, offline sync, Kubernetes, webhook
delivery, audit export, automatic merge/conflict resolution, or complex
path-level permissions.

TASK_012 extends the known SQLite MVP migration ledger with
`0012_project_api_tokens` for the project-scoped API token baseline.

## Ledger Table

`schema_migrations`:

- `id`
- `description`
- `applied_at`

The table is append-only. SQLite triggers reject direct updates and deletes:

- `trg_schema_migrations_no_update`
- `trg_schema_migrations_no_delete`

## Migration Command

Apply the current SQLite MVP schema and record known baseline migrations:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\migrate_db.py
```

Check migration status without initializing a missing DB:

```powershell
python scripts\migrate_db.py --status
```

## Status Policy

- `ok`: all expected migration IDs are present and no unknown rows exist.
- `pending`: expected migration IDs are missing.
- `drift`: unknown migration rows exist.

`init_db` and `scripts/init_db.py` also record known migration rows after the
schema is brought to the current baseline.

## Legacy SQLite MVP Databases

Legacy databases that predate `schema_migrations` are upgraded idempotently by
the existing schema creation and compatibility steps. After the schema is
current, TASK_011 records the known migration IDs as a backfilled baseline.

This means the ledger is reliable for future changes, but it is not a
historical audit of when old pre-ledger changes originally happened.

## Integrity Boundaries

- Migration bookkeeping does not create `document_events`.
- Migration bookkeeping does not mutate JSON document snapshots.
- The replay invariant remains the correctness gate:

```text
Replay(DocumentEvent[0..N]) == json_documents.current_snapshot_json
```

## Future Work

- PostgreSQL migration.
- External migration framework selection.
- Production migration rollback policy.
- Migration backup/restore gate.
- CI migration check from previous baseline fixtures.
