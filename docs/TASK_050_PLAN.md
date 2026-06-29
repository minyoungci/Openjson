# TASK_050 Plan - SQLite Restore Manifest Verification

## Goal

Verify SQLite backup manifests before restoring backup files.

`scripts/backup_sqlite.py` writes a manifest with backup size, SHA-256, and the
combined database integrity envelope. Restore should check that adjacent
manifest before copying the backup into the target path so a tampered backup is
rejected early.

## Non-Goals

- No production backup scheduler.
- No encryption, remote object storage, or retention policy.
- No DB schema change.
- No document/event/snapshot repair.
- No realtime collaboration, WebSocket, offline sync, or merge automation.
- No Git integration, branching, pull request workflow, or AI features.
- No UI work.
- No complex path-level permission model.

## CLI Behavior

`python scripts\restore_sqlite.py --backup-path <backup.sqlite3> --target-db-path <target.sqlite3>`

Restore looks for the adjacent manifest:

```text
<backup>.manifest.json
```

If the manifest exists:

- parse it as JSON
- compare `sha256` with the current backup file hash
- compare `size_bytes` with the current backup file size
- fail before writing the target database when either check mismatches

If the adjacent manifest is absent, restore remains compatible and proceeds,
but the result includes a manifest verification status of `not_found`.

## Data Model

No schema change.

This is an operational guard around local SQLite backup/restore files.

## Tests

- Backup manifest file includes the same manifest path returned to callers.
- Restore includes an `ok` manifest verification result when the backup matches
  its manifest.
- Restore rejects a tampered backup before creating the target DB.
- Restore CLI exits non-zero and prints the failed manifest verification
  payload for a tampered backup.
