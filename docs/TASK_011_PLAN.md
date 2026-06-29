# TASK_011 Plan: Managed Migration Baseline

TASK_011 adds a minimal managed migration baseline for the current SQLite MVP.

This task does not add PostgreSQL migration, Alembic, SQLAlchemy, production
authentication, password login, token issuance, enterprise SSO, billing, UI
work, realtime collaboration, WebSocket, Git integration, branching, pull
requests, AI features, offline sync, Kubernetes, webhook delivery, audit
export, automatic merge/conflict resolution, or complex path-level
permissions.

## Scope

- Add an append-only `schema_migrations` ledger table.
- Record the known baseline migration IDs during `init_db`.
- Add a migration/status command for local and staging smoke checks.
- Include migration state in `scripts/init_db.py` output.
- Keep existing SQLite schema initialization idempotent.

## Scripts

- `scripts/migrate_db.py`

## Data Model

`schema_migrations`:

- `id`
- `description`
- `applied_at`

The ledger is append-only through SQLite triggers.

## Integrity Policy

- Migration bookkeeping must not mutate JSON document snapshots.
- Migration bookkeeping must not create `document_events`.
- Existing replay consistency invariant remains unchanged.
- Legacy databases are upgraded idempotently and receive baseline migration
  records after the schema is made current.

## Acceptance Gate

- `python -m unittest discover -v` passes.
- `python -m compileall app tests scripts` passes.
- Migration command is idempotent.
- Migration status detects pending or unknown migration rows.
- Legacy baseline DB migration preserves document/event replay consistency.
- No forbidden product scope is implemented.

## Limitations

- This is not yet a PostgreSQL migration.
- This is not yet a full external migration framework.
- Historical migration records are backfilled as a current baseline for legacy
  SQLite MVP databases.
