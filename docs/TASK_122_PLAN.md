# TASK_122_PLAN.md

## Goal

Add a release preflight CLI that makes the current Render deployment handoff
inspectable before sharing the official URL.

This task does not add collaborative editing features. It only hardens the
deployment workflow around the existing application.

## Scope

- Add `scripts/release_preflight.py`.
- Check local Git release readiness:
  - worktree clean
  - current branch is `main`
  - branch is not ahead or behind upstream
  - origin points at `minyoungci/Openjson`
  - current commit is reported in the output
- Check required deployment runtime files:
  - `Dockerfile`
  - `render.yaml`
  - `requirements.txt`
  - deployment smoke and migration scripts
- Check Render Blueprint guard settings:
  - Docker runtime
  - Starter plan
  - manual deploy
  - one instance
  - `/health` health check
  - persistent disk at `/data`
  - production guard environment variables
- Optionally run the official deployment status smoke against:
  - `/health`
  - `/ready`
  - `/version`
  - `/app`
- Print structured JSON with `status`, per-check diagnostics, current commit,
  and next actions.

## Usage

Local-only preflight:

```powershell
python scripts\release_preflight.py
```

Official URL preflight after a manual Render deploy:

```powershell
python scripts\release_preflight.py `
  --base-url https://openjson.thelumen.work `
  --expect-actor-header-allowed false
```

When `--base-url` is provided and `--expect-commit` is omitted, the script uses
the local short Git commit as the expected deployed commit.

## Failure Policy

The CLI exits nonzero when any required check fails.

If the official URL reports `VERSION_ENDPOINT_NOT_FOUND` or
`READINESS_MIGRATION_STATUS_MISSING`, the URL is serving an older build. The
next action is to open Render Dashboard, run a manual deploy for the latest
`main` commit, and rerun the preflight.

## Exclusions

- No Render API integration.
- No Cloudflare API integration.
- No product feature changes.
- No WebSocket, CRDT, offline sync, email, auth, schema, or document model
  changes.
- No UI changes.
