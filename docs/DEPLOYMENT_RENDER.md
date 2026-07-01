# Render Deployment

This document describes the initial managed deployment path for OpenJson.

## Deployment Shape

- Platform: Render
- Source: GitHub repository
- Runtime: Docker
- Service: one web service
- Storage: SQLite on an attached Render persistent disk
- Disk mount: `/data`
- Database path: `/data/openjson.sqlite3`
- Public URL: `https://openjson.thelumen.work`
- Auto deploy: disabled
- Instance count: 1
- Disk size: 1 GB

This is the fastest practical deployment path for the current codebase. It is
single-instance by design. Move to PostgreSQL before scaling to multiple app
instances.

## Required Render Resources

The repository includes `render.yaml`.

Render will create:

- `openjson` web service
- `openjson-data` persistent disk mounted at `/data`

The service uses the `starter` plan because persistent disks require a paid web
service.

## Cost Controls

The repository-side deployment limits are:

```text
plan=starter
numInstances=1
disk.sizeGB=1
autoDeploy=false
```

This keeps compute and persistent disk capacity fixed for the initial
deployment. `autoDeploy=false` prevents every GitHub push from starting a new
build automatically. Deploy manually from the Render Dashboard when a change is
ready.

Render Dashboard settings to apply manually:

1. Open Workspace Settings.
2. Go to Build Pipeline.
3. Keep the Starter pipeline tier.
4. Click Set spend limit.
5. Set the pipeline spend limit to `0` if allowed. If Render requires a positive
   value, use the lowest allowed value.

Render currently documents a monthly spend limit for pipeline minutes. Outbound
bandwidth is usage-based after the included monthly allowance, so monitor it
from the Billing page and Render Metrics. Put Cloudflare in front of the custom
domain before public launch so basic abuse controls and rate limits can be
applied outside Render.

## Environment Variables

Configured by `render.yaml`:

```text
OPENJSON_DB_PATH=/data/openjson.sqlite3
OPENJSON_PUBLIC_BASE_URL=https://openjson.thelumen.work
OPENJSON_CORS_ORIGINS=https://openjson.thelumen.work
OPENJSON_EMAIL_BACKEND=console
OPENJSON_REQUEST_LOGGING=1
OPENJSON_ALLOW_ACTOR_HEADER=0
OPENJSON_RATE_LIMIT_ENABLED=1
OPENJSON_RATE_LIMIT_REQUESTS=120
OPENJSON_RATE_LIMIT_WINDOW_SECONDS=60
OPENJSON_WS_RATE_LIMIT_ENABLED=1
OPENJSON_WS_RATE_LIMIT_MESSAGES=120
OPENJSON_WS_RATE_LIMIT_WINDOW_SECONDS=60
OPENJSON_REQUEST_BODY_LIMIT_ENABLED=1
OPENJSON_MAX_REQUEST_BODY_BYTES=10485760
OPENJSON_PROJECT_USAGE_LIMIT_ENABLED=1
OPENJSON_MAX_PROJECT_DOCUMENTS=10000
OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES=104857600
```

`OPENJSON_ALLOW_ACTOR_HEADER=0` disables the development-only actor id fallback
on the public deployment. The browser app uses session bearer tokens, and
tokenless `X-Actor-Id` HTTP requests or WebSocket `actor_id` connections are
rejected.

The repository also enables a conservative in-process HTTP rate limit for the
single-instance deployment. Limited responses return `RATE_LIMITED` with HTTP
429 and `Retry-After`. `/health` and `/ready` are exempt so Render health
checks keep working. This is not a replacement for Cloudflare abuse controls;
keep Cloudflare proxied on the public domain before broader sharing.
WebSocket collaboration also has a separate per-connection message limit.
Limited sockets receive a structured `RATE_LIMITED` payload and close.
Oversized HTTP request bodies return `REQUEST_BODY_TOO_LARGE` with HTTP 413
before endpoint handlers parse or mutate application data. The default Render
limit is 10 MiB, matching the current ZIP archive limit.
Project usage limits reject create/save/restore/rollback/ZIP import mutations
with `PROJECT_USAGE_LIMIT_EXCEEDED` before document event or snapshot writes.
The default Render guard is 10,000 active documents and 100 MiB of active latest
snapshot JSON per project.

For manual encrypted SQLite backups from the Render shell or an attached
operational job, add a secret environment variable:

```text
OPENJSON_BACKUP_ENCRYPTION_KEY=<generated Fernet key>
```

Generate the key locally with:

```powershell
python scripts\backup_sqlite.py --generate-encryption-key
```

Do not commit the key. Encrypted backups use `.sqlite3.enc` and must be
restored with the same key.

For a restore drill after configuring the key:

```bash
python scripts/backup_restore_drill.py \
  --db-path "$OPENJSON_DB_PATH" \
  --output-dir /data/backups \
  --encrypt \
  --retention-count 7 \
  --report-path /data/backups/latest-drill-report.json
```

The drill writes a JSON report and exits nonzero unless both backup integrity
and restored database integrity pass.

For real email delivery, switch `OPENJSON_EMAIL_BACKEND` to `smtp` and add:

```text
OPENJSON_EMAIL_FROM=
OPENJSON_SMTP_HOST=
OPENJSON_SMTP_PORT=587
OPENJSON_SMTP_USERNAME=
OPENJSON_SMTP_PASSWORD=
OPENJSON_SMTP_TLS=1
```

After those values are configured in Render, run a manual deploy or restart the
service. New project invitations will then attempt SMTP delivery immediately
and will still record the attempt in `email_deliveries`. The UI keeps the invite
token visible as a fallback if SMTP delivery fails.

For OIDC SSO, add:

```text
OPENJSON_OIDC_ISSUER=
OPENJSON_OIDC_CLIENT_ID=
OPENJSON_OIDC_CLIENT_SECRET=
OPENJSON_OIDC_REDIRECT_URI=https://openjson.thelumen.work/auth/oidc/callback
OPENJSON_OIDC_AUTHORIZATION_ENDPOINT=
OPENJSON_OIDC_TOKEN_ENDPOINT=
OPENJSON_OIDC_JWKS_URI=
```

For the built-in single-instance SQLite daily backup scheduler, `render.yaml`
enables:

```text
OPENJSON_BACKUP_SCHEDULER_ENABLED=1
OPENJSON_BACKUP_OUTPUT_DIR=/data/backups
OPENJSON_BACKUP_INTERVAL_SECONDS=86400
OPENJSON_BACKUP_RETENTION_COUNT=7
OPENJSON_BACKUP_ENCRYPT=1
OPENJSON_BACKUP_ENCRYPTION_KEY=<secret>
```

Set `OPENJSON_BACKUP_ENCRYPTION_KEY` in Render before treating scheduled
backups as healthy. Generate it locally with:

```powershell
python scripts\backup_sqlite.py --generate-encryption-key
```

Render cron jobs cannot access the web service persistent disk, so this
scheduler runs inside the single web service instance that owns `/data`.
When encrypted scheduled backups are enabled, `/ready` fails with HTTP 503 if
the encryption key secret is missing. This prevents a deployment from looking
ready while the daily backup job is guaranteed to fail.

## Deploy Steps

1. Push this repository to GitHub.
2. Run the local release preflight:

```powershell
python scripts\release_preflight.py
```

The preflight should return `"status": "ok"` before the Render deploy. If it
reports a dirty worktree, a non-`main` branch, an out-of-sync upstream, missing
runtime or operation files, or a broken `render.yaml` guard, fix that first.
Operation files include the replay/integrity checks, backup and restore
scripts, backup encryption helper, and SQLite backup restore drill. See
`docs/TASK_126_PLAN.md`.

3. Open the Render Blueprint URL:

```text
https://dashboard.render.com/blueprint/new?repo=https://github.com/minyoungci/Openjson
```

4. Connect GitHub if Render asks for access.
5. Review the Blueprint resources.
6. Apply the Blueprint.
7. Wait until the service is live.
8. Apply the Cost Controls above in Workspace Settings.
9. Add `openjson.thelumen.work` as a custom domain in Render.
10. In Cloudflare DNS, create:

```text
Type: CNAME
Name: openjson
Target: <render service hostname>
Proxy: ON
```

## Post-Deploy Smoke Checks

After the service is live:

```text
GET https://openjson.thelumen.work/health
GET https://openjson.thelumen.work/ready
GET https://openjson.thelumen.work/version
GET https://openjson.thelumen.work/app
```

`/ready` should report `database.migrations.status=ok`. If it returns 503 with
pending or drifted migrations, run the current migration/init flow against the
persistent database before treating the deploy as live.
It should also report `operations.backup_scheduler.status=ok`. If it returns
503 with `operations.backup_scheduler.status=misconfigured`, set
`OPENJSON_BACKUP_ENCRYPTION_KEY` in Render and redeploy or restart the service.

`/version` should show the deployed Git commit from Render's
`RENDER_GIT_COMMIT` default environment variable and
`runtime_config.actor_header_allowed=false`. It should also show
`runtime_config.rate_limit_enabled=true` and
`runtime_config.websocket_rate_limit_enabled=true`, plus
`runtime_config.request_body_limit_enabled=true` and
`runtime_config.project_usage_limit_enabled=true`.

You can run the deployment status smoke from this repo:

```powershell
python scripts\smoke_deployment_status.py `
  --base-url https://openjson.thelumen.work `
  --expect-commit <git-sha> `
  --expect-actor-header-allowed false `
  --expect-backup-scheduler-enabled true `
  --expect-backup-encryption-key-configured true
```

The combined release/deployment preflight also checks local Git readiness,
Render Blueprint guard settings, and the official URL:

```powershell
python scripts\release_preflight.py `
  --base-url https://openjson.thelumen.work `
  --expect-actor-header-allowed false `
  --expect-backup-scheduler-enabled true `
  --expect-backup-encryption-key-configured true
```

The smoke prints structured JSON even when it fails. If the diagnostics include
`VERSION_ENDPOINT_NOT_FOUND`, the public URL is not serving a build that
contains `GET /version`; run a manual Render deploy from the latest `main`
commit and verify the Cloudflare CNAME still points at the Render service.
If diagnostics include `READINESS_MIGRATION_STATUS_MISSING`, `/ready` is also
coming from an older build that predates the migration readiness gate.
If diagnostics include `READY_BACKUP_SCHEDULER_MISCONFIGURED`, the deployment
is serving the current readiness surface but the scheduled encrypted backup key
secret is missing.

Then create an account from the UI and run a small document flow:

1. Create workspace/project.
2. Create a JSON document.
3. Edit and save.
4. Confirm history/checkpoint appears.
5. Open the same document in another browser session.
6. Confirm WebSocket presence and checkpoint updates.

## Known Limitations

- SQLite plus persistent disk is single-instance only.
- `OPENJSON_EMAIL_BACKEND=console` records invitation deliveries and prints the
  accept URL to logs, but does not send actual invitation emails.
- The public deployment disables the local `X-Actor-Id` / WebSocket
  `actor_id` fallback; use login/session tokens through the UI.
- HTTP rate limiting is per-process fixed-window state. It is sufficient for
  the initial single-instance Render service, but Cloudflare and/or Redis
  should enforce distributed limits before scaling.
- WebSocket message limiting is per-connection and in-process. It does not
  replace distributed connection limits or Cloudflare abuse controls.
- The SQLite backup scheduler is in-process and single-instance. Remote object
  storage lifecycle management is not provisioned in this Render baseline.
- OIDC SSO is disabled until provider environment variables are configured.
- Redis fanout is not provisioned in this baseline deployment.
- PostgreSQL migration is required before serious production scale.
