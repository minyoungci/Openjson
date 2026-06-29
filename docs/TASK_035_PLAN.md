# TASK_035 Plan - SQLite Database Integrity Envelope

## Goal

Extend the combined database integrity envelope so local/staging smoke checks
also verify SQLite-level database consistency.

TASK_034 combined replay consistency and event-chain metadata checks. That
proves the document event model is replayable, but it does not prove the SQLite
database still satisfies foreign key constraints or passes SQLite's structural
integrity check. TASK_035 adds those read-only checks to the same operational
gate.

TASK_036 later extends the same envelope with migration ledger integrity checks.

## Non-Goals

- No document mutation, event mutation, snapshot repair, or event compaction.
- No new persisted integrity table or cache.
- No schema migration or data model change.
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
      "status": "ok",
      "foreign_key_check": {
        "status": "ok",
        "failure_count": 0,
        "failures": []
      },
      "integrity_check": {
        "status": "ok",
        "messages": ["ok"]
      }
    }
  }
}
```

## Data Model

No schema change.

The checker uses managed SQLite connections with `PRAGMA foreign_keys = ON`.
It reads SQLite diagnostic PRAGMAs and does not write repair state.

## Tests

- Combined checker reports SQLite integrity status on a healthy database.
- Combined checker and CLI fail when `PRAGMA foreign_key_check` reports a
  broken foreign key.
- Existing replay and event-chain failure tests keep reporting SQLite status
  independently.
- Backup and restore smoke tests assert the expanded combined integrity
  envelope.
