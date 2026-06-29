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
```

For real email delivery, switch `OPENJSON_EMAIL_BACKEND` to `smtp` and add:

```text
OPENJSON_EMAIL_FROM=
OPENJSON_SMTP_HOST=
OPENJSON_SMTP_PORT=587
OPENJSON_SMTP_USERNAME=
OPENJSON_SMTP_PASSWORD=
OPENJSON_SMTP_TLS=1
```

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
GET https://openjson.thelumen.work/app
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
- `OPENJSON_EMAIL_BACKEND=console` does not send actual invitation emails.
- OIDC SSO is disabled until provider environment variables are configured.
- Redis fanout is not provisioned in this baseline deployment.
- PostgreSQL migration is required before serious production scale.
