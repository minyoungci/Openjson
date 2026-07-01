# DEV_USAGE.md

This workspace exposes local bootstrap APIs and a seed script for Swagger and
smoke testing. It also supports project-scoped API tokens for local/staging
automation, local password-backed sessions, refresh-token rotation, project
invitation tokens, invitation email delivery, and an OIDC SSO baseline. It is
still not enterprise SAML/SCIM identity management.

## Start Server

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Swagger UI:

- http://127.0.0.1:8000/docs

Local editor shell:

- http://127.0.0.1:8000/
- http://127.0.0.1:8000/app

User-facing login, project creation, save, realtime checkpoint, and memo flow:

- `docs/USER_WORKFLOW.md`

## Initialize DB

The app initializes the SQLite schema on startup. You can also initialize it
explicitly:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\init_db.py
```

Managed migration smoke command:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\migrate_db.py
python scripts\migrate_db.py --status
```

To reset local dev data:

```powershell
Remove-Item -LiteralPath "D:\OpenJson\openjson.sqlite3" -Force
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\init_db.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Deployment smoke endpoints:

- `GET /health`
- `GET /version`
- `GET /ready`

`GET /ready` also checks the schema migration ledger and non-secret backup
scheduler readiness. A response is ready only when
`database.migrations.status` is `ok`; pending or drifted migrations return HTTP
503 with the standard error envelope. If encrypted scheduled backups are
enabled without `OPENJSON_BACKUP_ENCRYPTION_KEY`, `/ready` returns HTTP 503 with
`operations.backup_scheduler.status = "misconfigured"`.

Optional local usage limits:

```powershell
$env:OPENJSON_RATE_LIMIT_ENABLED = "1"
$env:OPENJSON_RATE_LIMIT_REQUESTS = "120"
$env:OPENJSON_RATE_LIMIT_WINDOW_SECONDS = "60"
$env:OPENJSON_WS_RATE_LIMIT_ENABLED = "1"
$env:OPENJSON_WS_RATE_LIMIT_MESSAGES = "120"
$env:OPENJSON_WS_RATE_LIMIT_WINDOW_SECONDS = "60"
$env:OPENJSON_REQUEST_BODY_LIMIT_ENABLED = "1"
$env:OPENJSON_MAX_REQUEST_BODY_BYTES = "10485760"
$env:OPENJSON_PROJECT_USAGE_LIMIT_ENABLED = "1"
$env:OPENJSON_MAX_PROJECT_DOCUMENTS = "10000"
$env:OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES = "104857600"
```

Limited requests return `RATE_LIMITED` with HTTP 429. `/health`, `/ready`, and
`OPTIONS` are exempt.
Limited WebSocket collaboration connections receive a structured
`RATE_LIMITED` error payload and then close.
Oversized HTTP request bodies return `REQUEST_BODY_TOO_LARGE` with HTTP 413.
Project usage limit failures return `PROJECT_USAGE_LIMIT_EXCEEDED` before
document events or snapshots are written.

## Operational Smoke Commands

Non-realtime shared edit HTTP smoke:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
python scripts\smoke_shared_edit_flow.py --base-url http://127.0.0.1:8000
```

This smoke creates unique owner/editor users, a workspace, a project, and one
document. It then verifies `editor-state`, patch-preview, accepted patch,
workflow/state-machine metadata, `VERSION_CONFLICT` on stale editor save,
project editor bootstrap, raw-content conflict preview, reload/resave, history
event ids, and document replay integrity. Stale preview/save conflicts also
include the editor-state reload hint and latest accepted event metadata. See
`docs/TASK_087_PLAN.md`, `docs/TASK_088_PLAN.md`,
`docs/TASK_092_PLAN.md`, `docs/TASK_093_PLAN.md`,
`docs/TASK_094_PLAN.md`, and `docs/TASK_095_PLAN.md`.

Team workspace HTTP smoke:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
python scripts\smoke_team_workspace_flow.py --base-url http://127.0.0.1:8000
```

This smoke creates unique owner/editor users, invites the teammate into a
project, creates a JSON document, has the teammate save a versioned edit, checks
the collaboration checkpoint, adds and reopens a path-level note, verifies notes
do not mutate the document version or snapshot, and checks diff plus replay
consistency. See `docs/TASK_111_PLAN.md`.

Deployment status smoke:

```powershell
python scripts\smoke_deployment_status.py --base-url http://127.0.0.1:8000
```

Release preflight before sharing or redeploying:

```powershell
python scripts\release_preflight.py
```

This verifies the local Git state, Render Blueprint guard settings, deployment
runtime files, and the operation scripts required for integrity checks,
backup, restore, and the SQLite backup restore drill. See
`docs/TASK_122_PLAN.md` and `docs/TASK_126_PLAN.md`.

Derived compacted document snapshots:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\compact_document_snapshots.py
```

This writes immutable `document_snapshots` rows only after the event replay
invariant is verified. It does not delete or rewrite `document_events`.

For the official URL after a manual Render deploy:

```powershell
python scripts\smoke_deployment_status.py `
  --base-url https://openjson.thelumen.work `
  --expect-commit <git-sha> `
  --expect-actor-header-allowed false `
  --expect-backup-scheduler-enabled true `
  --expect-backup-encryption-key-configured true
```

Or run the combined release/deployment preflight:

```powershell
python scripts\release_preflight.py `
  --base-url https://openjson.thelumen.work `
  --expect-actor-header-allowed false `
  --expect-backup-scheduler-enabled true `
  --expect-backup-encryption-key-configured true
```

This smoke checks `/health`, `/ready`, `/version`, and `/app`. It is read-only
and does not create users, projects, documents, or events. See
`docs/TASK_114_PLAN.md`, `docs/TASK_115_PLAN.md`, and
`docs/TASK_116_PLAN.md`. See `docs/TASK_117_PLAN.md` for WebSocket message
rate limiting and `docs/TASK_121_PLAN.md` for structured failure diagnostics.
See `docs/TASK_122_PLAN.md` for the release preflight CLI and
`docs/TASK_126_PLAN.md` for operation-script coverage. TASK_127 adds
`--expect-backup-scheduler-enabled true` and
`--expect-backup-encryption-key-configured true` for the Render daily backup
scheduler check. TASK_128 also makes `/ready` fail when encrypted scheduled
backups are enabled but the encryption key secret is missing.
If the official URL returns `VERSION_ENDPOINT_NOT_FOUND`, the custom domain is
not yet serving a build that includes `/version`; trigger a manual Render deploy
from the latest `main` commit and rerun the smoke.
If it returns `READINESS_MIGRATION_STATUS_MISSING`, the public `/ready` route is
also from an older build and should be resolved by the same manual deploy.
If it returns `READY_BACKUP_SCHEDULER_MISCONFIGURED`, set
`OPENJSON_BACKUP_ENCRYPTION_KEY` in Render and redeploy or restart the service.

Local non-realtime editor shell:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/app`, sign up or log in, then create or open a
project. The browser app uses session bearer tokens, not manually pasted
`actor_id` values. The shell uses the same versioned save, preview, validation,
conflict preview, history, diff, and rollback APIs as Swagger. See
`docs/TASK_096_PLAN.md` and `docs/TASK_112_PLAN.md`.
The shell also supports shareable local URLs such as
`/app?project_id=<project_id>&document_id=<document_id>`, browser-local JSON
file import, and non-realtime conflict recovery controls.
Share URLs do not include bearer tokens. See `docs/TASK_097_PLAN.md`.
The shell also renders bound schema metadata and previews create-time
file-pattern schema matches from existing read-only schema APIs. See
`docs/TASK_098_PLAN.md`.
Schema validation failures from create, preview, or save are rendered in the
Validation inspector with JSON Pointer paths and validator details. See
`docs/TASK_099_PLAN.md`.
The shell also supports ZIP JSON import preview/apply for existing folder-like
JSON archives. See `docs/TASK_100_PLAN.md`.
The shell also shows realtime-style collaboration monitoring: active users,
dirty/stale base state, recent accepted checkpoints, and an optional autosave
toggle. See `docs/TASK_101_PLAN.md`.
The shell also includes local team onboarding controls and a WebSocket
presence/checkpoint channel. See `docs/TASK_102_PLAN.md`.
The shell also supports local signup/login, invitation-token create/accept,
WebSocket token authentication, and a conservative auto-merge toggle for stale
full-content saves on non-overlapping object paths. See
`docs/TASK_103_PLAN.md`.
The shell now also supports transient live text operations, live-text commit,
local offline save queue flushing, refresh-token rotation, invite email delivery
status, full invite-link copy controls, and invite-link signup/login
auto-accept.
It is still not full offline-first replicated storage or general conflict
auto-resolution. See `docs/TASK_104_PLAN.md`, `docs/TASK_107_PLAN.md`, and
`docs/TASK_108_PLAN.md`. See `docs/TASK_109_PLAN.md` for invite-link
onboarding. See `docs/TASK_110_PLAN.md` for the Notes panel over existing
comment-thread APIs.

Local session and invitation smoke:

```powershell
$owner = curl.exe -s -X POST http://127.0.0.1:8000/auth/signup `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"owner@example.com\",\"display_name\":\"Owner\",\"password\":\"local-password-123\"}" | ConvertFrom-Json

$editor = curl.exe -s -X POST http://127.0.0.1:8000/auth/signup `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"editor@example.com\",\"display_name\":\"Editor\",\"password\":\"local-password-123\"}" | ConvertFrom-Json

curl.exe -X POST http://127.0.0.1:8000/workspaces `
  -H "Authorization: Bearer $($owner.token)" `
  -H "Content-Type: application/json" `
  -d "{\"name\":\"Team Workspace\"}"
```

Refresh-token smoke:

```powershell
curl.exe -X POST http://127.0.0.1:8000/auth/refresh `
  -H "Content-Type: application/json" `
  -d "{\"refresh_token\":\"<ojr_refresh_token>\"}"
```

OIDC SSO baseline:

```powershell
$env:OPENJSON_OIDC_ISSUER = "https://issuer.example.com"
$env:OPENJSON_OIDC_CLIENT_ID = "<client-id>"
$env:OPENJSON_OIDC_CLIENT_SECRET = "<client-secret>"
$env:OPENJSON_OIDC_REDIRECT_URI = "https://app.example.com/auth/oidc/callback"
$env:OPENJSON_OIDC_AUTHORIZATION_ENDPOINT = "https://issuer.example.com/oauth2/v1/authorize"
$env:OPENJSON_OIDC_TOKEN_ENDPOINT = "https://issuer.example.com/oauth2/v1/token"
$env:OPENJSON_OIDC_JWKS_URI = "https://issuer.example.com/oauth2/v1/keys"
```

Invitation email delivery:

```powershell
$env:OPENJSON_PUBLIC_BASE_URL = "https://app.example.com"
$env:OPENJSON_EMAIL_BACKEND = "smtp" # disabled, console, smtp
$env:OPENJSON_EMAIL_FROM = "OpenJson <noreply@example.com>"
$env:OPENJSON_SMTP_HOST = "smtp.example.com"
$env:OPENJSON_SMTP_PORT = "587"
$env:OPENJSON_SMTP_USERNAME = "<smtp-user>"
$env:OPENJSON_SMTP_PASSWORD = "<smtp-password>"
$env:OPENJSON_SMTP_TLS = "1"
```

After creating a workspace and project, invite another signed-up user:

```powershell
$invite = curl.exe -s -X POST http://127.0.0.1:8000/projects/<project_id>/invitations `
  -H "Authorization: Bearer $($owner.token)" `
  -H "Content-Type: application/json" `
  -d "{\"email\":\"editor@example.com\",\"role\":\"editor\"}" | ConvertFrom-Json

curl.exe -X POST http://127.0.0.1:8000/invitations/accept `
  -H "Authorization: Bearer $($editor.token)" `
  -H "Content-Type: application/json" `
  -d "{\"token\":\"$($invite.token)\"}"
```

ZIP JSON import smoke:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/projects/project_dev/imports/zip-preview" `
  -H "X-Actor-Id: user_dev" `
  -H "Content-Type: application/zip" `
  --data-binary "@D:\path\team-json.zip"

curl.exe -X POST "http://127.0.0.1:8000/projects/project_dev/imports/zip-apply?reason=Initial%20team%20JSON%20import" `
  -H "X-Actor-Id: user_dev" `
  -H "Content-Type: application/zip" `
  --data-binary "@D:\path\team-json.zip"
```

Preview reports JSON file candidates, skipped non-JSON members, folder counts,
schema file-pattern matches, active path conflicts, schema validation failures,
and simple `.json` reference edges. Apply reruns the same checks in one write
transaction. If any file is blocked, no imported documents or events are
written. On success each JSON file is imported as a normal versioned document
with a `create` document event.

Project usage smoke:

```powershell
curl.exe "http://127.0.0.1:8000/projects/project_dev/usage" `
  -H "X-Actor-Id: user_dev"
```

Raw JSON editor content save:

```powershell
curl.exe -X POST http://127.0.0.1:8000/documents/<document_id>/content-preview `
  -H "Content-Type: application/json" `
  -H "X-Actor-Id: <actor_id>" `
  -d "{\"base_version\":1,\"content\":{\"model\":\"candidate\",\"learning_rate\":0.02}}"

curl.exe -X PUT http://127.0.0.1:8000/documents/<document_id>/content `
  -H "Content-Type: application/json" `
  -H "X-Actor-Id: <actor_id>" `
  -d "{\"base_version\":1,\"content\":{\"model\":\"candidate\",\"learning_rate\":0.02},\"reason\":\"raw editor save\"}"
```

These endpoints generate and return `generated_patch`; accepted saves still
write normal append-only `document_events` update rows. See
`docs/TASK_089_PLAN.md`.

To ask the server to safely auto-merge a stale full-content save, include
`merge_strategy`:

```powershell
curl.exe -X PUT http://127.0.0.1:8000/documents/<document_id>/content `
  -H "Content-Type: application/json" `
  -H "X-Actor-Id: <actor_id>" `
  -d "{\"base_version\":1,\"content\":{\"model\":\"candidate\",\"owner_note\":\"ok\"},\"merge_strategy\":\"auto\",\"reason\":\"safe auto merge\"}"
```

Auto-merge only accepts non-overlapping object-path changes. Overlaps,
ancestor/descendant overlaps, any array-sensitive path, schema failures, or
replay inconsistency return a structured error and create no event.

For raw editor text, send `content_text` instead of `content`:

```powershell
curl.exe -X POST http://127.0.0.1:8000/documents/<document_id>/content-preview `
  -H "Content-Type: application/json" `
  -H "X-Actor-Id: <actor_id>" `
  -d "{\"base_version\":1,\"content_text\":\"{\\\"model\\\":\\\"candidate\\\",\\\"learning_rate\\\":0.02}\"}"
```

Malformed `content_text` returns `INVALID_JSON_SYNTAX` with line, column, and
position diagnostics and does not write a document event. See
`docs/TASK_090_PLAN.md`.

`GET /documents/<document_id>/editor-state` also returns
`document.content_text`, a deterministic pretty JSON string generated from the
latest canonical snapshot. Use it as the initial raw editor buffer, then save
back through `PUT /documents/<document_id>/content` with `content_text`. See
`docs/TASK_091_PLAN.md`.

The same editor-state response includes `workflow`, a read-only action
contract for the non-realtime editor. Use `workflow.required_base_version` as
the `base_version` for accepted save calls, inspect `workflow.actions` for
role-derived availability, and follow `workflow.save_contract.recovery` after a
`VERSION_CONFLICT`. See `docs/TASK_093_PLAN.md`.
`workflow.state_machine` adds the screen-state contract for `clean`, `dirty`,
`syntax_invalid`, `preview_ready`, `saving`, `saved`, `validation_failed`,
`stale_conflict`, and `conflict_preview`. It is metadata only; only accepted
save success creates a document event. See `docs/TASK_094_PLAN.md`.

For the initial project editor screen, use project editor bootstrap:

```powershell
curl.exe "http://127.0.0.1:8000/projects/<project_id>/editor-bootstrap?selected_document_id=<document_id>&recent_events_limit=1" `
  -H "X-Actor-Id: <actor_id>"
```

This response combines project metadata, actor capabilities, a paged document
list, a folder-like document tree, and the optional selected document
editor-state. It is read-only and does not create document events. See
`docs/TASK_095_PLAN.md`.

Document collaboration monitoring:

```powershell
curl.exe "http://127.0.0.1:8000/documents/<document_id>/collaboration-state?since_version=1" `
  -H "X-Actor-Id: user_dev"

curl.exe -X POST "http://127.0.0.1:8000/documents/<document_id>/presence" `
  -H "Content-Type: application/json" `
  -H "X-Actor-Id: user_dev" `
  -d "{\"status\":\"editing\",\"base_version\":1,\"dirty\":true}"

curl.exe -X DELETE "http://127.0.0.1:8000/documents/<document_id>/presence" `
  -H "X-Actor-Id: user_dev"
```

`collaboration-state` reports active users and accepted checkpoints from
`document_events`. Autosave in the local UI uses
`PUT /documents/<document_id>/content`, so accepted autosaves create ordinary
append-only update events.

WebSocket collaboration notification channel:

```text
WS /ws/documents/<document_id>/collaboration?actor_id=user_dev
WS /ws/documents/<document_id>/collaboration?token=ojs_<session token>
```

Supported client messages:

```json
{"type":"presence","status":"editing","base_version":1,"dirty":true}
{"type":"refresh","since_version":1}
{"type":"ping"}
{"type":"text_session.join"}
{"type":"text_session.op","client_id":"browser-1","base_text_revision":0,"op":{"type":"insert","index":0,"text":" "}}
{"type":"text_session.commit","text_revision":1}
```

The server sends `collaboration_state`, `pong`, or structured `error`
messages. Browser clients use this channel for active-user and checkpoint
updates, but accepted saves still use `PUT /documents/<document_id>/content`
with `base_version`.

Offline sync batch:

```powershell
curl.exe -X POST http://127.0.0.1:8000/projects/<project_id>/offline-sync `
  -H "Authorization: Bearer <session_token>" `
  -H "Content-Type: application/json" `
  -d "{\"items\":[{\"client_operation_id\":\"local-1\",\"document_id\":\"<document_id>\",\"base_version\":1,\"content_text\":\"{\\\"value\\\":2}\"}]}"
```

The server returns per-item `applied`, `conflict`, or `failed`; successful
items create ordinary append-only document events.

For multi-process local experiments, set a Redis URL before starting every app
process:

```powershell
$env:OPENJSON_REDIS_URL = "redis://127.0.0.1:6379/0"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Local team UI smoke:

1. Sign up or log in as the project owner and open the project.
2. In the Team panel, create an invite for the second user's email address.
3. Copy the generated invite link or raw token.
4. In another browser profile/window, open the invite link, sign up or log in
   with the invited email address, and confirm the app opens the invited
   project after accepting the invite. If the wrong email is logged in, the
   token remains available for manual retry.
5. Open the same document in two browser windows with different logged-in
   users and confirm active users/checkpoints update through WebSocket with
   HTTP polling fallback.
6. Enable Auto-merge only for non-overlapping object-field edits; array edits
   and same-path edits should still show a conflict.

For stale non-realtime raw editor saves, preview client/server changes before
asking the user to reload or reconcile:

```powershell
curl.exe -X POST http://127.0.0.1:8000/documents/<document_id>/content-conflict-preview `
  -H "Content-Type: application/json" `
  -H "X-Actor-Id: <actor_id>" `
  -d "{\"base_version\":1,\"content_text\":\"{\\\"model\\\":\\\"candidate\\\",\\\"learning_rate\\\":0.02}\"}"
```

The response includes `client_changes`, `server_changes`, `conflicts`,
`has_conflicts`, `base_content_text`, `current_content_text`, and
`candidate_content_text`. It is read-only and does not create events. See
`docs/TASK_092_PLAN.md`.

Replay consistency:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\check_replay_consistency.py
```

Event-chain integrity:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\check_event_chain_integrity.py
```

Combined database integrity:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\check_database_integrity.py
```

This command runs replay consistency, event-chain metadata integrity,
`PRAGMA foreign_key_check`, `PRAGMA integrity_check`, and migration ledger
integrity. See `docs/TASK_035_PLAN.md` and `docs/TASK_036_PLAN.md`.
Malformed persisted snapshot or event JSON is reported as structured integrity
failure; see `docs/TASK_037_PLAN.md`.

Project-scoped replay integrity API:

```powershell
$headers = @{ "X-Actor-Id" = "user_dev" }
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects/project_dev/integrity/replay" `
  -Headers $headers
```

Project-scoped event-chain integrity API:

```powershell
$headers = @{ "X-Actor-Id" = "user_dev" }
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects/project_dev/integrity/events" `
  -Headers $headers
```

Document-scoped replay integrity API:

```powershell
$headers = @{ "X-Actor-Id" = "user_dev" }
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/documents/<document_id>/integrity/replay" `
  -Headers $headers
```

Document event-chain integrity API:

```powershell
$headers = @{ "X-Actor-Id" = "user_dev" }
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/documents/<document_id>/integrity/events" `
  -Headers $headers
```

Project-wide validation report API:

```powershell
$headers = @{ "X-Actor-Id" = "user_dev_editor" }
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects/project_dev/validation-report" `
  -Headers $headers
```

The validation report keeps schema validation `status` separate from
`integrity.status`. Check `integrity.status` to confirm replay consistency and
event-chain metadata integrity for the checked documents.
Malformed persisted snapshot or event JSON is returned as structured
validation/integrity failure in this report.

SQLite MVP backup:

```powershell
python scripts\backup_sqlite.py --db-path "D:\OpenJson\openjson.sqlite3" --output-dir "D:\OpenJson\backups"
```

The backup manifest reports a combined `integrity` status. It is `ok` only
when replay consistency, event-chain metadata integrity, and SQLite integrity
checks pass, with migration ledger integrity included in the same envelope.

To keep only the latest seven local backup files:

```powershell
python scripts\backup_sqlite.py --db-path "D:\OpenJson\openjson.sqlite3" --output-dir "D:\OpenJson\backups" --retention-count 7
```

You can also set `$env:OPENJSON_BACKUP_RETENTION_COUNT = "7"`. Retention runs
only after the new backup passes the combined integrity check.

Encrypted SQLite MVP backup:

```powershell
python scripts\backup_sqlite.py --generate-encryption-key
$env:OPENJSON_BACKUP_ENCRYPTION_KEY = "<generated-key>"
python scripts\backup_sqlite.py `
  --db-path "D:\OpenJson\openjson.sqlite3" `
  --output-dir "D:\OpenJson\backups" `
  --encrypt `
  --retention-count 7
```

Encrypted backups use `.sqlite3.enc`. The manifest records ciphertext and
plaintext verification metadata, but not the key. Keep
`OPENJSON_BACKUP_ENCRYPTION_KEY` in the deployment secret store, not in source
control.

SQLite MVP restore smoke:

```powershell
python scripts\restore_sqlite.py --backup-path "<backup sqlite path>" --target-db-path "D:\OpenJson\restored.sqlite3"
```

When an adjacent `.manifest.json` exists, restore verifies the backup file
`sha256` and `size_bytes` before writing the target DB.
Malformed manifest JSON fails before target DB creation. Missing manifests are
reported as `manifest_verification.status=not_found` and restore continues for
backward compatibility.
For encrypted backups, set `OPENJSON_BACKUP_ENCRYPTION_KEY` before restore.
Missing or wrong keys fail before target DB creation.

SQLite backup restore drill:

```powershell
$env:OPENJSON_BACKUP_ENCRYPTION_KEY = "<generated-key>"
python scripts\backup_restore_drill.py `
  --db-path "D:\OpenJson\openjson.sqlite3" `
  --output-dir "D:\OpenJson\backups" `
  --encrypt `
  --retention-count 7 `
  --report-path "D:\OpenJson\backups\latest-drill-report.json"
```

The drill creates an integrity-checked backup, restores it into a temporary
SQLite database, verifies combined integrity on the restored DB, and removes
the temporary restored DB unless `--keep-restored` is provided. See
`docs/TASK_125_PLAN.md`.

Single-instance SQLite backup scheduler:

```powershell
$env:OPENJSON_BACKUP_SCHEDULER_ENABLED = "1"
$env:OPENJSON_BACKUP_OUTPUT_DIR = "D:\OpenJson\backups"
$env:OPENJSON_BACKUP_INTERVAL_SECONDS = "86400"
$env:OPENJSON_BACKUP_RETENTION_COUNT = "7"
$env:OPENJSON_BACKUP_ENCRYPT = "1"
$env:OPENJSON_BACKUP_ENCRYPTION_KEY = "<generated-key>"
```

When enabled, the FastAPI app starts an in-process background task that reuses
`scripts\backup_sqlite.py` to create integrity-checked encrypted backups. This
is intended for the current single-instance SQLite deployment, not for
multi-instance scaling or PostgreSQL. If `OPENJSON_BACKUP_ENCRYPT = "1"` but
`OPENJSON_BACKUP_ENCRYPTION_KEY` is missing, `GET /ready` returns HTTP 503
instead of reporting the deployment ready. See `docs/TASK_127_PLAN.md` and
`docs/TASK_128_PLAN.md`.

Optional structured request logging:

```powershell
$env:OPENJSON_REQUEST_LOGGING = "1"
```

## Seed Dev User, Workspace, Project

In a second terminal:

```powershell
$env:OPENJSON_DB_PATH = "D:\OpenJson\openjson.sqlite3"
python scripts\seed_dev.py
```

The script is idempotent and prints the IDs to use in Swagger:

```json
{
  "db_path": "D:\\OpenJson\\openjson.sqlite3",
  "actor_id": "user_dev",
  "editor_actor_id": "user_dev_editor",
  "reviewer_actor_id": "user_dev_reviewer",
  "viewer_actor_id": "user_dev_viewer",
  "workspace_id": "workspace_dev",
  "project_id": "project_dev",
  "project_role": "owner"
}
```

Use `X-Actor-Id: user_dev` on owner-level document and schema requests.
Use `user_dev_editor` to create/apply review requests, `user_dev_reviewer` to
approve or request changes, and `user_dev_viewer` to test read-only access.
TASK_003 enforces project membership on both mutation and read APIs.

## API Token Smoke Test

Project-scoped API tokens are useful for smoke tests that should not pass
`X-Actor-Id` on every request.

1. Seed dev data with `python scripts\seed_dev.py`.
2. `POST /projects/project_dev/api-tokens` with `X-Actor-Id=user_dev`.
3. Copy the returned `token`. It is shown only once.
4. Retry project or document requests with:

```text
Authorization: Bearer <token>
```

5. Confirm `GET /projects/project_dev` succeeds with the token.
6. Confirm `GET /workspaces` fails with `PERMISSION_DENIED`.
7. `DELETE /projects/project_dev/api-tokens/{token_id}` to revoke it.
8. Confirm the revoked token fails with `AUTH_REQUIRED`.

## Project Export Smoke Test

The export API returns a JSON archive of project metadata, schemas, latest
document snapshots, and document event history. It is not Git integration and
does not create export files on disk.
The archive `integrity.status` is `ok` only when both replay consistency and
event-chain metadata integrity pass for the exported documents.
Malformed persisted snapshot or event JSON is returned as structured
document/event diagnostics in the archive, with `integrity.status` set to
`failed`.

```powershell
$headers = @{ "X-Actor-Id" = "user_dev" }
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/projects/project_dev/export?include_comments=true&include_reviews=true" `
  -Headers $headers
```

Only project owner/admin roles can export. Viewer/editor/reviewer users should
receive `PERMISSION_DENIED`.

## Bootstrap With API

You can also create bootstrap data through Swagger:

1. `POST /users`
2. Copy the returned `id`.
3. `POST /workspaces` with `X-Actor-Id` set to that user id.
4. `POST /workspaces/{workspace_id}/projects` with the same `X-Actor-Id`.
5. Use the returned project id for document, schema, comment, and review APIs.

This is still not full auth. `POST /users` creates a local user row only and
does not issue passwords, tokens, sessions, invitations, or workspace roles.
Use `/auth/signup` and `/auth/login` when you need a local bearer session.

## Swagger Test Order

1. Seed dev data with `python scripts\seed_dev.py`.
2. `POST /projects/{project_id}/documents` with `project_id=project_dev` and `X-Actor-Id=user_dev`.
3. Copy the returned `id`.
4. `GET /projects/{project_id}/documents` to confirm the document appears in the project list.
5. `GET /projects/{project_id}/document-tree` to inspect the folder-like document path tree.
6. Optional ZIP onboarding: `POST /projects/{project_id}/imports/zip-preview`
   with raw `application/zip` bytes, then
   `POST /projects/{project_id}/imports/zip-apply` only if `can_apply=true`.
7. `GET /projects/{project_id}/editor-bootstrap?selected_document_id={document_id}` to load project editor metadata, document list/tree, and the selected document editor-state.
8. `GET /documents/{document_id}`.
9. `GET /documents/{document_id}/integrity/replay` to verify replay consistency for one document.
10. `GET /documents/{document_id}/integrity/events` to verify event-chain metadata for one document.
11. `POST /documents/{document_id}/patch-preview` with the current `base_version` to inspect the candidate snapshot without creating an event. See `docs/TASK_081_PLAN.md` for the preview permission, soft-delete, and malformed snapshot boundary.
12. `POST /documents/{document_id}/content-conflict-preview` with an existing
    stale `base_version` to inspect client/server path overlaps without
    creating an event. See `docs/TASK_092_PLAN.md`.
13. `POST /documents/{document_id}/validate` to confirm the current snapshot
    validation result and the `current_version` that result belongs to. See
    `docs/TASK_082_PLAN.md`.
14. `PATCH /documents/{document_id}` with the current `base_version`.
15. `GET /documents/{document_id}/history`.
16. `GET /documents/{document_id}/history/1` to reconstruct the version 1 snapshot.
17. Copy an event `id`, then `GET /documents/{document_id}/events/{event_id}?include_snapshots=true`.
18. `GET /documents/{document_id}/path-history?path=/learning_rate`.
19. `GET /documents/{document_id}/blame?path=/learning_rate`.
20. `GET /projects/{project_id}/document-events?changed_path=/learning_rate` to inspect recent accepted document mutations across the project.
21. `GET /projects/{project_id}/activity` to inspect the owner/admin project activity timeline.
22. `GET /projects/{project_id}/schema-matches?full_path=config/model.json` to preview file-pattern schema binding.
23. `GET /schemas/{schema_id}/usage` to inspect bound documents and latest validation state for one schema.
24. `GET /projects/{project_id}/document-search?q=learning_rate` to find latest snapshots by path, JSON key, or scalar value.
25. `GET /documents/{document_id}/diff?from_version=1&to_version=2`.
26. `POST /documents/{document_id}/rollback` with the current `base_version` and `target_version=1`.
27. `GET /documents/{document_id}` again and confirm the rollback result.
28. Optional: `DELETE /documents/{document_id}` and then `POST /documents/{document_id}/restore` with the deleted document's current `base_version`.

## Swagger Audit Log Test Order

1. Seed dev data with `python scripts\seed_dev.py`.
2. Create another user with `POST /users`.
3. `POST /projects/{project_id}/members` with `X-Actor-Id=user_dev`.
4. Optionally retry the same add to produce a rejected duplicate attempt.
5. `GET /projects/{project_id}/audit-log` with `X-Actor-Id=user_dev`.
6. Confirm success and failure membership events are listed.
7. Retry the audit read with `X-Actor-Id=user_dev_viewer` and confirm `PERMISSION_DENIED`.

## Swagger Review Test Order

1. Seed dev data with `python scripts\seed_dev.py`.
2. Create a document with `X-Actor-Id=user_dev`.
3. `POST /projects/{project_id}/review-requests` with `X-Actor-Id=user_dev_editor`.
4. `POST /review-requests/{review_request_id}/approve` with `X-Actor-Id=user_dev_reviewer`.
5. `POST /review-requests/{review_request_id}/apply` with `X-Actor-Id=user_dev_editor`.
6. `GET /documents/{document_id}/history` and confirm apply created a normal document event.

TASK_001 intentionally excludes realtime collaboration, comments, review workflow, Git integration, AI features, branching, pull requests, and UI work.

See `docs/TASK_001_BASELINE.md` for the approved TASK_001/TASK_001_HARDENING implementation policy.

See `docs/TASK_002_PLAN.md` for the JSON Schema validation and schema registry policy.

See `docs/TASK_002_BASELINE.md` for the approved TASK_002/TASK_002_HARDENING baseline.

See `docs/RBAC_BASELINE.md` for the approved TASK_003 minimal project-level RBAC baseline.

See `docs/COMMENTS_BASELINE.md` for the approved TASK_004 comments/memo baseline.

See `docs/REVIEW_BASELINE.md` for the approved TASK_005 JSON-native review workflow baseline.

See `docs/TASK_005_HARDENING.md` for the review workflow hardening policy.

See `docs/WORKSPACE_PROJECT_BASELINE.md` for the approved TASK_006 minimal
workspace/project API baseline.

See `docs/TASK_006_HARDENING.md` for the TASK_006 HTTP and transaction
hardening policy.

See `docs/API_SPEC.md` and `docs/DATA_MODEL.md` for the standard API and data
model entrypoints.

See `docs/TASK_047_PLAN.md` for malformed persisted audit log details JSON
diagnostics.

See `docs/TASK_048_PLAN.md` for project activity document-event malformed JSON
diagnostics.

See `docs/TASK_049_PLAN.md` for document search malformed latest snapshot
partial diagnostics.

See `docs/TASK_050_PLAN.md` for SQLite restore manifest verification.

See `docs/TASK_051_PLAN.md` for SQLite restore manifest missing/malformed edge
case policy.

See `docs/TASK_007_PLAN.md` and `docs/PROJECT_MEMBERSHIP_BASELINE.md` for the
minimal project membership management policy.

See `docs/TASK_007_HARDENING.md` for membership owner-protection and access
revocation hardening.

See `docs/TASK_008_PLAN.md` and `docs/AUDIT_LOG_BASELINE.md` for the minimal
append-only operational audit log policy.

See `docs/TASK_009_PLAN.md` and `docs/DEPLOYMENT_BASELINE.md` for the minimal
deployment hardening baseline.

See `docs/TASK_010_PLAN.md` and `docs/OPERATIONS_BASELINE.md` for the minimal
observability, replay check, and SQLite MVP backup baseline.

See `docs/TASK_011_PLAN.md` and `docs/MIGRATIONS_BASELINE.md` for the managed
SQLite MVP migration ledger baseline.

See `docs/TASK_012_PLAN.md` and `docs/AUTH_BASELINE.md` for the minimal
project-scoped API token authentication baseline.

See `docs/TASK_053_PLAN.md` for API token audit atomicity hardening.

See `docs/TASK_054_PLAN.md` for API token schema resource-scope hardening.

See `docs/TASK_055_PLAN.md` for API token document mutation actor attribution
hardening.

See `docs/TASK_056_PLAN.md` for API token restore and rollback actor
attribution hardening.

See `docs/TASK_057_PLAN.md` for API token replay-dependent read surface
hardening.

See `docs/TASK_058_PLAN.md` for API token path history and blame read surface
hardening.

See `docs/TASK_059_PLAN.md` for API token schema validation mutation
atomicity hardening.

See `docs/TASK_060_PLAN.md` for API token schema validation restore and
rollback atomicity hardening.

See `docs/TASK_061_PLAN.md` for API token document validate read-surface
hardening.

See `docs/TASK_062_PLAN.md` for empty update patch rejection hardening.

See `docs/TASK_063_PLAN.md` for multi-operation update patch atomicity
hardening.

See `docs/TASK_064_PLAN.md` for concrete array append changed path hardening.

See `docs/TASK_065_PLAN.md` for strict JSON Pointer escaping hardening.

See `docs/TASK_066_PLAN.md` for strict JSON Pointer read-filter hardening.

See `docs/TASK_067_PLAN.md` for HTTP JSON Pointer read-filter error hardening.

See `docs/TASK_068_PLAN.md` for strict document full_path validation
hardening.

See `docs/TASK_069_PLAN.md` for schema match full_path validation parity.

See `docs/TASK_070_PLAN.md` for strict document path_prefix filter hardening.

See `docs/TASK_071_PLAN.md` for strict schema file_pattern validation
hardening.

See `docs/TASK_072_PLAN.md` for case-sensitive schema file_pattern matching
hardening.

See `docs/TASK_073_PLAN.md` for inactive explicit schema binding rejection
hardening.

See `docs/TASK_074_PLAN.md` for existing inactive schema binding mutation
validation hardening.

See `docs/TASK_075_PLAN.md` for malformed schema JSON restore atomicity
hardening.

See `docs/TASK_084_PLAN.md` for invalid persisted JSON Schema mutation gate
atomicity hardening.

See `docs/TASK_076_PLAN.md` for delete/restore lifecycle event metadata
hardening.

See `docs/TASK_013_PLAN.md` for the minimal project document listing baseline.

See `docs/TASK_022_PLAN.md` for the read-only project document tree API.

See `docs/TASK_017_PLAN.md` for the read-only project document event feed.

See `docs/TASK_023_PLAN.md` for the read-only project activity timeline API.

See `docs/TASK_018_PLAN.md` for the read-only project document search API.

See `docs/TASK_019_PLAN.md` for the read-only project export archive API.

See `docs/TASK_020_PLAN.md` for the read-only project replay integrity API.

See `docs/TASK_021_PLAN.md` for the read-only project validation report API.

See `docs/TASK_033_PLAN.md` for the validation report integrity context.

See `docs/TASK_024_PLAN.md` for the read-only schema usage API.

See `docs/TASK_040_PLAN.md` for schema usage malformed JSON diagnostics.

See `docs/TASK_083_PLAN.md` for invalid persisted JSON Schema diagnostics on
read-only schema usage and validation-report surfaces.

See `docs/TASK_025_PLAN.md` for the read-only schema match preview API.

See `docs/TASK_026_PLAN.md` for the read-only document event detail API.

See `docs/TASK_041_PLAN.md` for document event detail malformed JSON
diagnostics.

See `docs/TASK_042_PLAN.md` for document history, project event feed,
path-history, and blame malformed event JSON diagnostics.

See `docs/TASK_043_PLAN.md` for replay-dependent malformed event JSON errors
on version, diff, and rollback surfaces.

See `docs/TASK_044_PLAN.md` for core document read and mutation malformed
latest snapshot diagnostics.

See `docs/TASK_045_PLAN.md` for malformed persisted schema JSON diagnostics.

See `docs/TASK_085_PLAN.md` for the read-only editor-facing document state API.

See `docs/TASK_086_PLAN.md` for accepted mutation response event metadata and
the non-realtime shared edit save contract.

See `docs/TASK_087_PLAN.md` for the HTTP shared-edit smoke script.

See `docs/TASK_093_PLAN.md` for editor-state workflow/action metadata for
non-realtime editor clients.

See `docs/TASK_094_PLAN.md` for editor-state screen state-machine metadata for
non-realtime editor clients.

See `docs/TASK_095_PLAN.md` for the read-only project editor bootstrap API for
initial project editor screen loads.

See `docs/TASK_096_PLAN.md` for the local non-realtime editor shell.

See `docs/TASK_097_PLAN.md` for shareable local editor URLs, browser-local
JSON file import, and non-realtime conflict recovery controls.

See `docs/TASK_098_PLAN.md` for schema-aware local editor display and
create-time schema match preview.

See `docs/TASK_099_PLAN.md` for schema validation failure diagnostics in the
local editor shell.

See `docs/TASK_100_PLAN.md` for ZIP JSON import preview/apply.

See `docs/TASK_101_PLAN.md` for realtime-style editor presence, checkpoint
monitoring, and local autosave.

See `docs/TASK_102_PLAN.md` for local team onboarding controls and the
WebSocket collaboration notification channel.

See `docs/TASK_103_PLAN.md` for local sessions, invitation tokens, WebSocket
token authentication, optional Redis fanout, and conservative safe auto-merge.

See `docs/TASK_104_PLAN.md` for transient text collaboration, invitation email
delivery, refresh-token rotation, OIDC SSO, and offline sync.

## Production Deployment Inputs Needed

Before real deployment, provide:

- production domain and public base URL;
- SMTP or transactional email provider credentials;
- OIDC provider issuer/client id/client secret/redirect URI/JWKS URI;
- PostgreSQL connection string and migration target;
- Redis URL for WebSocket fanout/presence;
- TLS/reverse proxy target and allowed CORS origins;
- secret-management location for app, SMTP, and OIDC secrets;
- backup retention, restore objective, and monitoring destination.

See `docs/TASK_046_PLAN.md` for malformed persisted review proposal JSON
diagnostics.

See `docs/TASK_027_PLAN.md` for the read-only document replay integrity API.

See `docs/TASK_028_PLAN.md` for the read-only document event-chain integrity
API.

See `docs/TASK_029_PLAN.md` for the read-only project event-chain integrity
API.

See `docs/TASK_030_PLAN.md` for the read-only event-chain consistency CLI.

See `docs/TASK_031_PLAN.md` for the backup/restore combined integrity
envelope.

See `docs/TASK_123_PLAN.md` for encrypted SQLite MVP backup/restore.

See `docs/TASK_032_PLAN.md` for the project export event-chain integrity
baseline.

See `docs/TASK_034_PLAN.md` for the combined database integrity CLI.

See `docs/TASK_035_PLAN.md` for the SQLite database integrity envelope.

See `docs/TASK_036_PLAN.md` for the migration ledger integrity envelope.

See `docs/TASK_037_PLAN.md` for malformed persisted JSON integrity diagnostics.

See `docs/TASK_038_PLAN.md` for validation report malformed JSON diagnostics.

See `docs/TASK_039_PLAN.md` for project export malformed JSON diagnostics.

See `docs/TASK_014_PLAN.md` for the minimal document version snapshot API
baseline.

See `docs/TASK_015_PLAN.md` for the minimal path history and blame baseline.

See `docs/TASK_016_PLAN.md` for the minimal soft-deleted document restore
baseline.
