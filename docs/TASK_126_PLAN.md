# TASK_126_PLAN.md

## Goal

Make the release preflight fail fast when the repository is missing the
operational scripts needed to verify SQLite backup and restore readiness.

This is a deployment hardening task. It does not add product features,
background schedulers, managed backup storage, or a PostgreSQL implementation.

## Scope

- Extend `scripts/release_preflight.py` required file checks beyond the web
  deployment files.
- Require the replay, event-chain, combined database integrity, backup,
  restore, backup encryption helper, and backup restore drill scripts.
- Keep the official URL smoke read-only.
- Add a regression test for a missing `scripts/backup_restore_drill.py`.
- Document that local release preflight now checks deployment and operations
  files before sharing or redeploying.

## Required Operation Files

The release preflight must verify that these files are present:

- `scripts/check_replay_consistency.py`
- `scripts/check_event_chain_integrity.py`
- `scripts/check_database_integrity.py`
- `scripts/backup_crypto.py`
- `scripts/backup_sqlite.py`
- `scripts/restore_sqlite.py`
- `scripts/backup_restore_drill.py`

## Verification

```powershell
python -m unittest tests.test_release_preflight
python -m compileall app scripts
python -m unittest discover -s tests
python scripts\release_preflight.py
```

The public deployment smoke remains a separate check:

```powershell
python scripts\release_preflight.py `
  --base-url https://openjson.thelumen.work `
  --expect-actor-header-allowed false
```

## Exclusions

- No automatic backup scheduling.
- No remote object storage upload.
- No managed backup provider integration.
- No PostgreSQL backup or point-in-time recovery.
- No new user-facing product UI.
