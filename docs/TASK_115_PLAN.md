# TASK_115 Plan: Readiness Migration Gate

## Objective

Make the public readiness check prove that the deployed SQLite database matches
the current code migration ledger before the service is treated as ready.

The official Render service can run code and persistent disk state from
different points in time when deployments are manual. `/ready` should detect
missing or unexpected migration rows instead of only checking table existence.

## Scope

- Include schema migration ledger status in `GET /ready`.
- Fail `GET /ready` with the standard error envelope and HTTP 503 when the
  migration ledger is pending or drifted.
- Keep the check read-only.
- Extend the deployment status smoke to call `/ready`.
- Document the readiness migration gate.

## Out of Scope

- Adding new database tables or migrations.
- Running expensive document replay checks on every readiness request.
- Automatic repair of migration drift.
- Render API automation, dashboard automation, deploy hooks, billing, SSO
  administration, Git import/export, branching, pull requests, or AI features.

## Data Model

No schema change.

## API

```text
GET /ready
```

Successful responses include:

```json
{
  "status": "ready",
  "database": {
    "connected": true,
    "foreign_keys_enabled": true,
    "migrations": {
      "status": "ok",
      "current_schema_version": "0015_deployment_collaboration_auth_sync"
    }
  }
}
```

If migrations are pending or drifted, `/ready` returns `INTERNAL_ERROR` with
HTTP 503 and the migration status under `error.details.database.migrations`.

## Test Plan

- `/ready` success includes migration status `ok`.
- `/ready` fails with pending migrations even when required tables exist.
- `/ready` fails with unknown migration drift.
- Deployment status smoke checks `/health`, `/ready`, `/version`, and `/app`.
