# TASK_037 Plan - Malformed Persisted JSON Integrity Diagnostics

## Goal

Make integrity checks fail closed with structured reports when persisted JSON
payloads are malformed.

The product invariant says invalid JSON must not become the canonical latest
snapshot, and persisted document events must remain replayable. If the database
is corrupted or manually tampered with, operational integrity commands should
report the corruption as integrity failure instead of crashing with a Python
`JSONDecodeError` traceback.

## Non-Goals

- No document mutation, event mutation, snapshot repair, or event compaction.
- No migration repair, migration deletion, or schema rewrite.
- No new persisted integrity table or cache.
- No scheduler, alerting, metrics stack, or production SRE program.
- No UI work.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No complex path-level permission model.

## Covered Diagnostics

Replay and event-chain integrity checks now treat malformed persisted JSON as
structured failure:

- malformed `json_documents.current_snapshot_json`
- malformed `document_events.patch`
- malformed `document_events.inverse_patch`
- malformed `document_events.changed_paths`
- malformed `document_events.before_values`
- malformed `document_events.after_values`

The failure includes:

- stable error code
- event id when the malformed field belongs to an event
- field name
- JSON decoder message
- line, column, and character position

## Error Codes

- `SNAPSHOT_JSON_DECODE_FAILED`
- `EVENT_JSON_DECODE_FAILED`

## CLI Behavior

```powershell
python scripts\check_database_integrity.py --db-path D:\OpenJson\openjson.sqlite3
```

The command still prints JSON to stdout and exits `1` when malformed persisted
JSON is detected. It should not emit a traceback for these expected corruption
diagnostics.

TASK_038 extends the same diagnostic policy to the project validation report
API.

## Data Model

No schema change.

The checker remains read-only. It reports malformed persisted JSON but does not
repair the snapshot or event log.

## Tests

- Replay checker reports malformed latest snapshot JSON.
- Event-chain checker reports malformed event JSON.
- Combined database integrity CLI returns structured JSON and nonzero exit
  status for malformed event JSON.
