# TASK_128_PLAN.md

## Goal

Harden deployment readiness for the SQLite backup scheduler.

TASK_127 added an opt-in in-process daily backup scheduler for the
single-instance Render SQLite deployment. This task makes readiness fail
explicitly when encrypted scheduled backups are enabled but the required
encryption key secret is missing.

## Scope

- Keep `GET /health` as a lightweight liveness endpoint.
- Keep `GET /version` as the non-secret runtime configuration surface.
- Extend `GET /ready` with non-secret operational readiness details for the
  backup scheduler.
- Return HTTP 503 with the standard `INTERNAL_ERROR` envelope when:
  - `OPENJSON_BACKUP_SCHEDULER_ENABLED=1`
  - `OPENJSON_BACKUP_ENCRYPT=1`
  - `OPENJSON_BACKUP_ENCRYPTION_KEY` is empty or unset
- Do not expose database paths, backup output paths, encryption keys, session
  tokens, API tokens, SMTP secrets, or OIDC secrets.

## Readiness Payload

Successful readiness includes:

```json
{
  "status": "ready",
  "operations": {
    "backup_scheduler": {
      "status": "ok",
      "configured": true,
      "enabled": true,
      "encrypt": true,
      "encryption_key_configured": true,
      "interval_seconds": 86400,
      "retention_count": 7
    }
  }
}
```

Misconfigured encrypted scheduled backups return:

```json
{
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "Readiness check failed.",
    "details": {
      "operations": {
        "backup_scheduler": {
          "status": "misconfigured",
          "enabled": true,
          "encrypt": true,
          "encryption_key_configured": false
        }
      }
    }
  }
}
```

## Verification

```powershell
python -m unittest tests.test_deployment_hardening
python -m compileall app scripts
python -m unittest discover -s tests
python scripts\release_preflight.py
```

After Render deploy:

```powershell
python scripts\release_preflight.py `
  --base-url https://openjson.thelumen.work `
  --expect-commit <git-sha> `
  --expect-actor-header-allowed false `
  --expect-backup-scheduler-enabled true `
  --expect-backup-encryption-key-configured true
```

## Exclusions

- No new database table.
- No backup job history persistence.
- No remote object storage integration.
- No alerting provider integration.
- No PostgreSQL backup or point-in-time recovery.
