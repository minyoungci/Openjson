# TASK_121 Plan: Deployment Smoke Failure Diagnostics

## Objective

Make the official deployment smoke useful when the public URL is not yet
serving the latest OpenJson app.

The current Render deployment is manual and `autoDeploy=false`, so GitHub can
be ahead of the code actually running at `https://openjson.thelumen.work`. The
smoke command should report that state as structured JSON instead of ending
with an opaque traceback.

## Scope

- Keep the successful deployment smoke behavior.
- Add a structured deployment status report used by the CLI.
- Probe `/health`, `/ready`, `/version`, and `/app` independently.
- Preserve each endpoint's HTTP status and response body summary.
- Return explicit diagnostics for common deployment problems, including:
  - missing `/version` route
  - readiness failure
  - stale `/ready` payload without migration status
  - deployed commit mismatch
  - actor-header configuration mismatch
  - unexpected app shell response
- Keep the command read-only.
- Add regression coverage for the stale-deploy `/version` 404 case.

## Command

```powershell
python scripts\smoke_deployment_status.py `
  --base-url https://openjson.thelumen.work `
  --expect-commit <git-sha> `
  --expect-actor-header-allowed false
```

On success, the command prints:

```json
{
  "status": "ok",
  "checks": {}
}
```

On failure, the command still prints JSON and exits nonzero:

```json
{
  "status": "failed",
  "checks": {
    "version": {
      "http_status": 404
    }
  },
  "diagnostics": [
    {
      "code": "VERSION_ENDPOINT_NOT_FOUND",
      "message": "The deployment is not serving a build that includes GET /version."
    }
  ]
}
```

## Data Model

No database schema changes.

The smoke is read-only and does not mutate users, workspaces, projects,
documents, document events, schemas, comments, reviews, sessions, audit rows,
or operational tables.

## Excluded

- Render API automation.
- Render dashboard automation.
- Deploy hooks.
- Cloudflare API changes.
- Auto-deploy enablement.
- Production observability pipeline.
