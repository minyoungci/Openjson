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

## Deploy Steps

1. Push this repository to GitHub.
2. Open the Render Blueprint URL:

```text
https://dashboard.render.com/blueprint/new?repo=https://github.com/minyoungci/Openjson
```

3. Connect GitHub if Render asks for access.
4. Review the Blueprint resources.
5. Apply the Blueprint.
6. Wait until the service is live.
7. Apply the Cost Controls above in Workspace Settings.
8. Add `openjson.thelumen.work` as a custom domain in Render.
9. In Cloudflare DNS, create:

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

`/version` should show the deployed Git commit from Render's
`RENDER_GIT_COMMIT` default environment variable and
`runtime_config.actor_header_allowed=false`. It should also show
`runtime_config.rate_limit_enabled=true` and
`runtime_config.websocket_rate_limit_enabled=true`.

You can run the deployment status smoke from this repo:

```powershell
python scripts\smoke_deployment_status.py `
  --base-url https://openjson.thelumen.work `
  --expect-commit <git-sha> `
  --expect-actor-header-allowed false
```

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
- OIDC SSO is disabled until provider environment variables are configured.
- Redis fanout is not provisioned in this baseline deployment.
- PostgreSQL migration is required before serious production scale.
