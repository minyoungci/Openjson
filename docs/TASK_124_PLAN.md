# TASK_124_PLAN.md

## Goal

Add a derived compacted document snapshot baseline for replay performance
hardening.

The canonical source of truth remains:

```text
latest json_documents.current_snapshot_json + append-only document_events
```

`document_snapshots` rows are immutable derived artifacts. They are generated
only after event replay is verified to reconstruct the current latest snapshot.

## Scope

- Add `document_snapshots`.
- Add immutable triggers for `document_snapshots`.
- Add `app.snapshot_compaction_service`.
- Add `scripts/compact_document_snapshots.py`.
- Add tests covering patch, rollback, delete/restore, duplicate compaction,
  and corrupt latest-snapshot refusal.

## Compaction Policy

- Default interval: every 100 accepted document versions.
- The latest version is also compacted by default for local operations.
- The script can compact one document/version explicitly.
- The script can list existing compacted snapshots for a document.
- Existing valid snapshot rows are treated idempotently.
- Existing rows that no longer match replay are reported as `INTERNAL_ERROR`.

## Safety Rules

- `document_events` are never rewritten, deleted, or compacted away.
- `json_documents.current_snapshot_json` is not changed by compaction.
- Compaction first verifies:
  - event JSON fields are parseable;
  - replay to `current_version` equals the latest stored snapshot;
  - requested target version exists in `document_events`.
- If replay and latest snapshot diverge, no `document_snapshots` row is written.

## CLI

```powershell
python scripts\compact_document_snapshots.py --db-path D:\OpenJson\openjson.sqlite3
```

Compact one document version:

```powershell
python scripts\compact_document_snapshots.py `
  --db-path D:\OpenJson\openjson.sqlite3 `
  --document-id <document_id> `
  --version 100
```

List snapshots for a document:

```powershell
python scripts\compact_document_snapshots.py `
  --db-path D:\OpenJson\openjson.sqlite3 `
  --document-id <document_id> `
  --list
```

## Exclusions

- No UI work.
- No new public HTTP endpoint.
- No event deletion or event-log compaction.
- No automatic scheduler.
- No background worker.
- No remote object storage.
- No PostgreSQL materialized snapshot implementation.
