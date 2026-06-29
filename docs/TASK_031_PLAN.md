# TASK_031 Plan - Backup and Restore Integrity Envelope

## Goal

Harden the local/staging SQLite backup and restore smoke scripts so their
reported integrity result covers both:

- replay consistency
- event-chain metadata integrity

TASK_030 made event-chain integrity available as a standalone CLI. TASK_031
threads that same check into backup and restore manifests so a database with a
correct final snapshot but corrupted event metadata is not reported as fully
healthy by operational backup smoke checks.

## Non-Goals

- No backup encryption, retention, scheduler, alerting, or production SRE
  program.
- No PostgreSQL backup/restore implementation.
- No mutation, repair, event rewrite, or snapshot rewrite.
- No new persisted integrity table or cache.
- No UI work.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No complex path-level permission model.

## Behavior

`scripts/backup_sqlite.py` and `scripts/restore_sqlite.py` should return an
integrity envelope:

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

The top-level integrity `status` is `ok` only when both checks are `ok`.
TASK_035 later extends this combined envelope with SQLite foreign key and
structural integrity checks. TASK_036 later extends it with migration ledger
integrity checks.

The CLI process exits `1` when the combined integrity status is not `ok`.

## Data Model

No schema change.

The checks read `json_documents` and `document_events` only.

## Tests

- Backup manifest includes replay, event-chain, SQLite, and migration ledger
  integrity checks.
- Restore result includes replay, event-chain, SQLite, and migration ledger
  integrity checks.
- Backup CLI exits nonzero when event-chain metadata fails even if final replay
  still matches the latest snapshot.
- Restore CLI exits nonzero for a backup whose event-chain metadata fails.
- The scripts remain source-database read-only.
