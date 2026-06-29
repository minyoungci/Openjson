# TASK_034 Plan - Combined Database Integrity CLI

## Goal

Add a read-only local/staging CLI that runs the combined database integrity
envelope in one command.

Existing operational commands can check replay consistency and event-chain
metadata separately. Backup/restore already use a combined integrity envelope.
TASK_034 exposes that same combined check directly for smoke tests and
deployment gates.

TASK_035 later extends this CLI envelope with SQLite foreign key and structural
integrity checks. TASK_036 later extends it with migration ledger integrity
checks.

## Non-Goals

- No document mutation, event mutation, snapshot repair, event compaction, or
  audit mutation.
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

- initializes the current SQLite schema if needed, matching the existing replay
  and event-chain checker behavior
- checks every `json_documents` row, including soft-deleted documents
- runs both replay consistency and event-chain metadata integrity checks
- prints a JSON report to stdout
- exits `0` when both checks pass
- exits `1` when either check fails

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
    }
  }
}
```

## Data Model

No schema change.

The checker reads `json_documents` and `document_events` only.

## Tests

- Combined checker CLI exits `0` when replay and event-chain checks pass.
- Combined checker CLI exits `1` when replay fails.
- Combined checker CLI exits `1` when event-chain metadata fails even if replay
  remains ok.
- The command remains read-only.
