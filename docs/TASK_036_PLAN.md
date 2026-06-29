# TASK_036 Plan - Migration Ledger Integrity Envelope

## Goal

Extend the combined database integrity envelope so local/staging smoke checks
also verify the SQLite schema migration ledger.

TASK_035 verifies document replay, event-chain metadata, SQLite foreign keys,
and SQLite structural integrity. TASK_036 adds the `schema_migrations` ledger
status to the same gate so unknown migration drift or pending migration state
is visible before backup, restore, or deployment smoke checks are treated as
healthy.

## Non-Goals

- No document mutation, event mutation, snapshot repair, or event compaction.
- No migration repair, migration deletion, or schema rewrite.
- No new persisted integrity table or cache.
- No scheduler, alerting, metrics stack, or production SRE program.
- No UI work.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No complex path-level permission model.

## CLI

```powershell
python scripts\check_database_integrity.py --db-path D:\OpenJson\openjson.sqlite3
```

Behavior:

- initializes the current SQLite schema if needed, matching existing smoke
  checker behavior
- checks every `json_documents` row, including soft-deleted documents
- runs replay consistency checks
- runs event-chain metadata integrity checks
- runs `PRAGMA foreign_key_check`
- runs `PRAGMA integrity_check`
- checks `schema_migrations` against the known migration baseline
- prints a JSON report to stdout
- exits `0` only when all checks pass
- exits `1` when any check fails

## Response Shape

```json
{
  "status": "ok",
  "checks": {
    "replay": {
      "status": "ok"
    },
    "event_chain": {
      "status": "ok"
    },
    "sqlite": {
      "status": "ok"
    },
    "migrations": {
      "status": "ok",
      "ledger_status": "ok",
      "current_schema_version": "0012_project_api_tokens",
      "expected_migrations": [
        "0001_document_foundation",
        "0002_schema_registry",
        "0003_project_rbac",
        "0004_comments",
        "0005_review_workflow",
        "0006_workspace_project_api",
        "0007_project_membership_management",
        "0008_audit_log",
        "0009_deployment_baseline",
        "0010_operations_baseline",
        "0011_managed_migration_baseline",
        "0012_project_api_tokens"
      ],
      "applied_count": 12,
      "pending_migrations": [],
      "unknown_migrations": []
    }
  }
}
```

## Data Model

No schema change.

The checker reads the existing append-only `schema_migrations` table through
`get_schema_migration_status()`. It reports non-`ok` migration status as a
combined integrity failure but does not repair the ledger.

## Tests

- Combined checker reports migration ledger status on a healthy database.
- Combined checker and CLI fail when an unknown migration row is present.
- Replay, event-chain, and SQLite failures still report migration status
  independently.
- Backup and restore smoke tests assert the expanded combined integrity
  envelope.
- Backup and restore report failure when migration ledger drift is present.
