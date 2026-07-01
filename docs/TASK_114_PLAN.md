# TASK_114 Plan: Deployment Version Surface

## Objective

Make the public deployment verifiable after manual Render deploys.

Render auto-deploy is intentionally disabled for cost control, so a pushed
commit is not necessarily the code currently running at
`https://openjson.thelumen.work`. This task adds a public, read-only deployment
status surface and a smoke script that can confirm which commit/config is live.

## Scope

- Add `GET /version`.
- Report safe runtime metadata:
  - service name
  - deployment platform
  - Git commit/branch/repo slug when provided by Render or explicit env vars
  - non-secret runtime config flags needed for deployment validation
- Add a smoke script for official/local URL checks.
- Document the endpoint and manual deploy verification flow.
- Add tests proving the endpoint is public, read-only, and secret-safe.

## Out of Scope

- Render API integration, dashboard automation, or deploy hooks.
- Exposing secrets, database paths, API tokens, SMTP credentials, or session
  data.
- Billing, SSO administration, Git import/export, branching, pull requests, or
  AI features.
- Changing document event, validation, diff, rollback, or collaboration
  persistence semantics.

## Data Model

No schema change.

## API

```text
GET /version
```

The response is public and read-only. It must not mutate the database.

## Test Plan

- `/version` is public and does not mutate document/event tables.
- Render/default env metadata is included when present.
- Secret-looking env values are not exposed.
- `scripts/smoke_deployment_status.py` passes against a TestClient-backed local
  app and can check a real base URL.
