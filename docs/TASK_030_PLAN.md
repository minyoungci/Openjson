# TASK_030 Plan - Event Chain Consistency CLI

## Goal

Add a read-only local/staging CLI for checking event-chain integrity across the
whole SQLite database.

Existing `scripts/check_replay_consistency.py` verifies the final invariant:

```text
Replay(document_events) == json_documents.current_snapshot_json
```

TASK_030 adds a complementary operational check for the event log metadata
itself. The command should fail if any document has a broken version chain,
unsupported event type, mismatched inverse patch, mismatched changed paths, or
mismatched before/after values.

## Non-Goals

- No document mutation, event mutation, snapshot repair, event compaction, or
  audit mutation.
- No new persisted integrity table or cache.
- No scheduler, background worker, alerting stack, or production SRE program.
- No UI work.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No complex path-level permission model.

## CLI

```powershell
python scripts\check_event_chain_integrity.py --db-path D:\OpenJson\openjson.sqlite3
```

Behavior:

- initializes the current SQLite schema if needed, matching the existing replay
  checker behavior
- checks every `json_documents` row, including soft-deleted documents
- prints a JSON report to stdout
- exits `0` when all checked documents pass
- exits `1` when one or more documents fail

## Response Shape

```json
{
  "status": "ok",
  "checked_documents": 2,
  "failure_count": 0,
  "failures": []
}
```

`failure_count` counts failed documents. Each failure is the same
per-document event-chain report used by the project/document integrity APIs.

## Data Model

No schema change.

The checker reads `json_documents` and `document_events` only.

## Tests

- Checker returns `ok` for create -> patch -> rollback -> delete -> restore.
- Checker reports metadata mismatch even when final replay still matches the
  latest snapshot.
- CLI exits `0` on success and `1` on failure.
- The command remains read-only.
