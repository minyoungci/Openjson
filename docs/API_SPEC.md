# API_SPEC.md

This document is the standard API entrypoint for the current backend
implementation.

The service is still a local MVP. It does not implement SAML/SCIM enterprise
administration, invitation email retry workers, full offline-first replicated
storage, Git integration, branching, pull requests, AI features, or complex
path-level permissions. TASK_096 adds a
local static editor shell, TASK_101 adds checkpoint/presence monitoring,
TASK_102 adds a WebSocket presence/checkpoint channel plus local team
onboarding controls, and TASK_103 adds local password sessions, invitation
tokens, token-aware WebSockets, optional Redis fanout, and conservative safe
auto-merge. TASK_104 adds transient text-operation collaboration, invitation
email delivery, refresh-token rotation, OIDC SSO baseline, and offline sync
batch APIs. Accepted document mutations still flow through the backend
version/event APIs.

## Authentication Boundary

`POST /users` is a bootstrap endpoint and does not require authentication.

TASK_103 supports local password-backed session tokens:

```text
Authorization: Bearer ojs_<session token>
```

Session tokens act as their user and still go through project RBAC. They are
stored only as token hashes in SQLite.

TASK_104 adds refresh-token rotation:

```text
POST /auth/refresh
```

Refresh tokens are one-time-use, stored only as hashes, and rotate to a new
access session plus a new refresh token. Reusing an old refresh token returns
`AUTH_REQUIRED`.

Local development requests may still use:

```text
X-Actor-Id: <user id>
```

TASK_012 also supports project-scoped API tokens:

```text
Authorization: Bearer <token>
```

API tokens are scoped to one project. They act as their owning user and still
go through project RBAC. Project tokens cannot access workspace bootstrap
endpoints.

OIDC SSO is available when `OPENJSON_OIDC_*` provider settings are configured.
This is not SAML, SCIM, enterprise domain policy administration, or a complete
managed identity product.

## Request ID Boundary

All HTTP responses include:

```text
X-Request-Id: <request id>
```

If the client supplies `X-Request-Id`, the server preserves it. Otherwise the
server generates one.

## Error Format

All API errors use:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message.",
    "details": {}
  }
}
```

## Local UI

- `GET /`
- `GET /app`
- `GET /static/styles.css`
- `GET /static/app.js`

The static browser UI calls the existing REST APIs with local session bearer
tokens and does not introduce a separate frontend persistence model.
`X-Actor-Id` remains available for local API development and legacy smoke
commands, but the official browser app no longer sends it as an identity
fallback. TASK_102 adds local user/member controls and a WebSocket
presence/checkpoint channel, but the editor still saves through the versioned
HTTP content API.

See `docs/TASK_096_PLAN.md`.
See `docs/TASK_097_PLAN.md` for shareable URL, browser-local JSON import, and
non-realtime conflict recovery controls.
See `docs/TASK_098_PLAN.md` for schema-aware editor display and create-time
schema match preview in the local UI.
See `docs/TASK_099_PLAN.md` for editor rendering of schema validation failure
diagnostics.
See `docs/TASK_100_PLAN.md` for ZIP JSON import preview/apply in the local UI.
See `docs/TASK_101_PLAN.md` for realtime-style presence, checkpoint
monitoring, and local autosave.
See `docs/TASK_102_PLAN.md` for local team onboarding controls and the
WebSocket collaboration notification channel.
See `docs/TASK_103_PLAN.md` for local sessions, invitation tokens,
token-aware WebSockets, optional Redis fanout, and safe auto-merge.
See `docs/TASK_104_PLAN.md` for transient text collaboration, invitation
email delivery, refresh-token rotation, OIDC SSO, and offline sync.
See `docs/TASK_107_PLAN.md` for invitation email delivery status rendering.
See `docs/TASK_108_PLAN.md` for full invite-link display and copy controls.
See `docs/TASK_109_PLAN.md` for invite-link signup/login auto-accept
onboarding.
See `docs/TASK_110_PLAN.md` for the local Notes panel over existing comment
thread APIs.
See `docs/TASK_111_PLAN.md` for the team workspace smoke covering signup,
invite, edit checkpoint, notes, diff, and replay.
See `docs/TASK_112_PLAN.md` for the production entry UX cleanup that removes
developer identity fallback from the static browser app.

## Bootstrap, Workspace, Project

- `GET /health`
- `GET /ready`
- `POST /auth/signup`
- `POST /auth/login`
- `POST /auth/logout`
- `POST /auth/refresh`
- `GET /auth/me`
- `GET /auth/oidc/login`
- `POST /auth/oidc/callback`
- `POST /users`
- `POST /workspaces`
- `GET /workspaces`
- `GET /workspaces/{workspace_id}`
- `POST /workspaces/{workspace_id}/projects`
- `GET /workspaces/{workspace_id}/projects`
- `GET /projects/{project_id}`
- `GET /projects/{project_id}/members`
- `POST /projects/{project_id}/members`
- `PATCH /projects/{project_id}/members/{user_id}`
- `DELETE /projects/{project_id}/members/{user_id}`
- `GET /projects/{project_id}/export`
- `GET /projects/{project_id}/integrity/replay`
- `GET /projects/{project_id}/integrity/events`
- `GET /projects/{project_id}/validation-report`
- `GET /projects/{project_id}/audit-log`
- `GET /projects/{project_id}/activity`
- `POST /projects/{project_id}/offline-sync`
- `POST /projects/{project_id}/api-tokens`
- `GET /projects/{project_id}/api-tokens`
- `DELETE /projects/{project_id}/api-tokens/{token_id}`
- `POST /projects/{project_id}/invitations`
- `GET /projects/{project_id}/invitations`
- `POST /invitations/accept`

See `docs/WORKSPACE_PROJECT_BASELINE.md` and `docs/TASK_006_HARDENING.md`.
See `docs/PROJECT_MEMBERSHIP_BASELINE.md` for project member management.
See `docs/AUDIT_LOG_BASELINE.md` for the minimal operational audit log.
See `docs/AUTH_BASELINE.md` for the minimal project API token boundary.
See `docs/TASK_054_PLAN.md` for API token schema resource-scope edge cases.
See `docs/TASK_055_PLAN.md` for API token document mutation actor attribution.
See `docs/TASK_056_PLAN.md` for API token restore and rollback actor attribution.
See `docs/TASK_057_PLAN.md` for API token replay read surface scope.
See `docs/TASK_058_PLAN.md` for API token path history and blame scope.
See `docs/TASK_059_PLAN.md` for API token schema validation mutation
atomicity.
See `docs/TASK_060_PLAN.md` for API token schema validation restore and
rollback atomicity.
See `docs/TASK_061_PLAN.md` for API token document validate read-surface
scope.
See `docs/TASK_082_PLAN.md` for document validate response context.
See `docs/TASK_080_PLAN.md` for API token document patch preview scope.
See `docs/TASK_081_PLAN.md` for document patch preview RBAC, lifecycle, and
malformed snapshot boundaries.
See `docs/TASK_019_PLAN.md` for the project export archive API.
See `docs/TASK_032_PLAN.md` for the project export event-chain integrity
policy.
See `docs/TASK_039_PLAN.md` for project export malformed JSON diagnostics.
See `docs/TASK_020_PLAN.md` for the project replay integrity API.
See `docs/TASK_029_PLAN.md` for the project event-chain integrity API.
See `docs/TASK_021_PLAN.md` for the project validation report API.
See `docs/TASK_033_PLAN.md` for the validation report integrity context.
See `docs/TASK_038_PLAN.md` for validation report malformed JSON diagnostics.
See `docs/TASK_023_PLAN.md` for the project activity timeline API.
See `docs/TASK_047_PLAN.md` for malformed persisted audit log details JSON
diagnostics.
See `docs/TASK_048_PLAN.md` for project activity document-event malformed JSON
diagnostics.

## Documents

- `POST /projects/{project_id}/documents`
- `GET /projects/{project_id}/documents`
- `GET /projects/{project_id}/document-tree`
- `GET /projects/{project_id}/editor-bootstrap`
- `POST /projects/{project_id}/imports/zip-preview`
- `POST /projects/{project_id}/imports/zip-apply`
- `GET /projects/{project_id}/document-events`
- `GET /projects/{project_id}/document-search?q=learning_rate`
- `GET /documents/{document_id}`
- `GET /documents/{document_id}/editor-state`
- `GET /documents/{document_id}/collaboration-state?since_version=1`
- `POST /documents/{document_id}/presence`
- `DELETE /documents/{document_id}/presence`
- `WS /ws/documents/{document_id}/collaboration?actor_id=user_dev`
- `WS /ws/documents/{document_id}/collaboration?token=ojs_<session token>`
- `GET /documents/{document_id}/integrity/replay`
- `GET /documents/{document_id}/integrity/events`
- `PATCH /documents/{document_id}`
- `POST /documents/{document_id}/patch-preview`
- `POST /documents/{document_id}/content-preview`
- `POST /documents/{document_id}/content-conflict-preview`
- `PUT /documents/{document_id}/content`
- `DELETE /documents/{document_id}`
- `POST /documents/{document_id}/restore`
- `GET /documents/{document_id}/history`
- `GET /documents/{document_id}/history/{version}`
- `GET /documents/{document_id}/events/{event_id}?include_snapshots=true`
- `GET /documents/{document_id}/path-history?path=/learning_rate`
- `GET /documents/{document_id}/blame?path=/learning_rate`
- `GET /documents/{document_id}/diff?from_version=1&to_version=2`
- `POST /documents/{document_id}/rollback`
- `POST /documents/{document_id}/validate`

See `docs/TASK_001_BASELINE.md` and `docs/TASK_002_BASELINE.md`.
See `docs/TASK_017_PLAN.md` for the project-scoped document event feed.
See `docs/TASK_018_PLAN.md` for the project-scoped latest snapshot search API.
See `docs/TASK_049_PLAN.md` for document search malformed latest snapshot
partial diagnostics.
See `docs/TASK_022_PLAN.md` for the project document tree API.
See `docs/TASK_026_PLAN.md` for the single document event detail API.
See `docs/TASK_041_PLAN.md` for document event detail malformed JSON
diagnostics.
See `docs/TASK_042_PLAN.md` for malformed event JSON diagnostics on document
history, project event feed, path-history, and blame read surfaces.
See `docs/TASK_043_PLAN.md` for structured malformed event JSON errors on
replay-dependent version, diff, and rollback surfaces.
See `docs/TASK_044_PLAN.md` for structured malformed latest snapshot errors on
core document read and mutation surfaces.
See `docs/TASK_027_PLAN.md` for the document-scoped replay integrity API.
See `docs/TASK_028_PLAN.md` for the document event-chain integrity API.
See `docs/TASK_062_PLAN.md` for empty update patch rejection.
See `docs/TASK_063_PLAN.md` for multi-operation update patch atomicity.
See `docs/TASK_064_PLAN.md` for concrete array append changed paths.
See `docs/TASK_065_PLAN.md` for strict JSON Pointer escaping.
See `docs/TASK_066_PLAN.md` for strict JSON Pointer read filters.
See `docs/TASK_067_PLAN.md` for HTTP JSON Pointer read-filter errors.
See `docs/TASK_068_PLAN.md` for strict document full_path validation.
See `docs/TASK_069_PLAN.md` for schema match full_path validation parity.
See `docs/TASK_070_PLAN.md` for strict document path_prefix filters.
See `docs/TASK_071_PLAN.md` for strict schema file_pattern validation.
See `docs/TASK_072_PLAN.md` for case-sensitive schema file_pattern matching.
See `docs/TASK_073_PLAN.md` for inactive explicit schema binding rejection.
See `docs/TASK_074_PLAN.md` for existing inactive schema binding mutation
validation.
See `docs/TASK_075_PLAN.md` for malformed schema JSON restore atomicity.
See `docs/TASK_084_PLAN.md` for invalid persisted JSON Schema mutation gate
atomicity.
See `docs/TASK_085_PLAN.md` for the read-only editor-facing document state
API.
See `docs/TASK_086_PLAN.md` for accepted document mutation response event
metadata and the non-realtime shared edit save contract.
See `docs/TASK_087_PLAN.md` for the HTTP smoke script that exercises the same
non-realtime shared edit contract against a running server.
See `docs/TASK_088_PLAN.md` for editor-facing `VERSION_CONFLICT` reload
diagnostics.
See `docs/TASK_089_PLAN.md` for raw JSON editor content preview/save APIs
that generate auditable JSON Patch events.
See `docs/TASK_090_PLAN.md` for `content_text` parsing and syntax diagnostics
on the raw JSON editor content APIs.
See `docs/TASK_091_PLAN.md` for editor-state `document.content_text` load
support for raw JSON editors.
See `docs/TASK_092_PLAN.md` for the read-only raw-content conflict preview API
for stale non-realtime editor saves.
See `docs/TASK_093_PLAN.md` for editor-state workflow/action metadata that
lets clients build the non-realtime editor flow from the API response.
See `docs/TASK_094_PLAN.md` for editor-state state-machine metadata for the
non-realtime editor screen.
See `docs/TASK_095_PLAN.md` for the project editor bootstrap aggregate that
loads project metadata, document list, document tree, and an optional selected
document editor-state in one read-only response.
See `docs/TASK_076_PLAN.md` for delete/restore lifecycle event metadata.
See `docs/TASK_077_PLAN.md` for rollback target version range hardening.
See `docs/TASK_078_PLAN.md` for semantic no-op update patch rejection.
See `docs/TASK_079_PLAN.md` for the read-only document patch preview API.
Patch preview requires the same document write permission as accepted patch
mutations, rejects soft-deleted documents, and does not persist events,
versions, snapshots, audit rows, or validation results.
Content preview and content save accept a full candidate JSON document for raw
editor workflows. The service recursively diffs the current snapshot against
the candidate, generates `add`, `remove`, and `replace` operations, and then
uses the same validation and update event pipeline as patch mutations. Accepted
content saves return `generated_patch` and still create a normal append-only
`event_type = "update"` row; previews return `generated_patch` but remain
read-only.
Content preview/save requests may provide exactly one of `content` or
`content_text`. `content_text` is parsed server-side for raw JSON editor
workflows. Malformed JSON text returns `INVALID_JSON_SYNTAX` with
`line`, `column`, and `position` diagnostics and does not create events or
change snapshots.
Content conflict preview accepts the same `content`/`content_text` candidate
shape but intentionally allows stale existing `base_version` values. It
reconstructs the base snapshot from `document_events`, compares client changes
against accepted server changes since that base, reports exact and
ancestor/descendant path overlaps as conflicts, and remains read-only.
Content save accepts optional `merge_strategy`. The default is `"reject"` and
keeps the original strict `base_version` conflict behavior. `"auto"` may be
used only for stale full-content saves where the client and server changed
non-overlapping object paths and no touched path crosses an array. The server
reconstructs the stale base snapshot, checks replay consistency, converts the
safe client delta into a new patch against the latest snapshot, and records a
normal append-only `event_type = "update"` event at the latest server version.
Overlapping paths, ancestor/descendant overlaps, array-sensitive paths, schema
failures, malformed content, or replay inconsistency reject without event or
snapshot writes.
Document validate responses include `document_id`, `project_id`, `full_path`,
`current_version`, `deleted_at`, and `schema_id` so editor-facing clients can
tie validation results to the snapshot version they checked.
Document editor-state responses are read-only composites for active editor
loads. They include the current document snapshot, required base version,
deterministic pretty JSON `document.content_text`, actor role/capabilities,
workflow/action metadata, bound schema metadata, optional validation state, and
recent events without mutating document events, snapshots, versions, audit
rows, or validation persistence.
The editor-state `workflow` block declares the non-realtime versioned edit
mode, canonical content source, base version field, save contract, and
role-derived action availability for reload, validation, patch/content preview,
content conflict preview, patch/content save, history, diff, and rollback.
The workflow `state_machine` block declares the read-only screen state
contract for client-owned local states such as `dirty` and `syntax_invalid`,
server-verified states such as `preview_ready`, `saved`, and
`stale_conflict`, allowed actions per state, transitions, and the rule that
only accepted save success creates a document event.
Project editor-bootstrap responses are read-only composites for the first
project editor screen load. They reuse the project document list, project
document tree, and optional document editor-state contracts, and they do not
create events, mutate snapshots, increment versions, write audit rows, or
persist validation results.
Project ZIP import preview accepts raw `application/zip` request bytes and is
read-only. It parses `.json` members, preserves ZIP member paths as candidate
document `full_path` values, reports folder counts, schema file-pattern matches,
syntax/schema errors, active path conflicts, skipped non-JSON files, and simple
JSON-file reference edges. It does not create import rows, documents, document
events, schemas, audit rows, or editor state.
Project ZIP import apply reruns the same checks in one write transaction. If
any candidate fails, the entire import is rejected with
`ZIP_IMPORT_PRECHECK_FAILED` and no partial documents or events are written. On
success each JSON member is created through the normal document create pipeline
as version `1` with an append-only `event_type = "create"` document event.
This is not Git import/export and does not introduce branching, pull requests,
merge resolution, background import jobs, or realtime collaboration.
Document collaboration-state is a read-only monitoring surface over active
editor presence and accepted `document_events` checkpoints. Presence rows are
transient operational state; they do not alter snapshots or document event
history. Autosave in the local editor calls the existing content save API, so
an accepted autosave is a normal append-only `event_type = "update"` document
event. TASK_102 exposes the same state over
`WS /ws/documents/{document_id}/collaboration?actor_id={actor_id}`. TASK_103
also accepts `token=ojs_<session token>` or an API token query parameter for
browser WebSocket clients. The WebSocket accepts `presence`, `refresh`,
`ping`, `text_session.join`, `text_session.op`, and `text_session.commit`
messages and sends `collaboration_state`, `pong`, `text_session.state`,
`text_session.op.accepted`, `text_session.committed`, or structured `error`
messages. Text session operations are transient OT-style insert/delete/replace
operations; they become durable only when `text_session.commit` parses the
current collaborative text as valid JSON and writes a normal append-only
document update event. `OPENJSON_REDIS_URL` enables optional Redis fanout
across app processes. It does not make raw text canonical storage and does not
persist syntax-invalid JSON.

Offline sync accepts a batch of queued client content-save operations:

```text
POST /projects/{project_id}/offline-sync
```

Each item requires `client_operation_id`, `document_id`, `base_version`, and
either `content` or `content_text`. The server applies each operation through
the existing content update pipeline and returns per-item `applied`,
`conflict`, or `failed` status. `client_operation_id` is idempotent per actor.
Accepted document mutation responses include `event_id` and `event_type`.
The returned `event_id` identifies the append-only `document_events` row that
records the accepted create, update, delete, restore, or rollback mutation.
Conflict responses such as `VERSION_CONFLICT` do not create events and do not
return accepted event metadata.
`VERSION_CONFLICT` details include the client/server versions, document
identity, `conflict_policy = "reject_stale_base_version"`, a reload hint for
`GET /documents/{document_id}/editor-state`, and the latest accepted
`document_events` metadata so non-realtime editors can explain the conflict and
reload the correct state.

## Schemas

- `POST /projects/{project_id}/schemas`
- `GET /projects/{project_id}/schemas`
- `GET /projects/{project_id}/schema-matches?full_path=config/model.json`
- `GET /schemas/{schema_id}`
- `GET /schemas/{schema_id}/usage`

Schema rows are immutable in the current implementation. There is no schema
update or deactivate API yet.

See `docs/TASK_024_PLAN.md` for the read-only schema usage API.
See `docs/TASK_040_PLAN.md` for schema usage malformed JSON diagnostics.
See `docs/TASK_083_PLAN.md` for read-only invalid persisted JSON Schema
diagnostics.
See `docs/TASK_025_PLAN.md` for the read-only schema match preview API.
See `docs/TASK_045_PLAN.md` for malformed persisted schema JSON diagnostics.
Schema file_pattern matching uses case-sensitive POSIX-style semantics on both
document auto-binding and schema match preview surfaces.
New document creation may only bind active schemas, including when `schema_id`
is provided explicitly.
Documents that already reference a schema keep validating against that bound
schema even if the schema row is inactive.
If a bound schema row contains malformed `schema_json`, schema-gated document
mutations fail before event or snapshot writes, including restore.
If a bound schema row contains parseable but invalid JSON Schema, schema-gated
document mutations also fail before event, snapshot, version, or lifecycle
writes with `SCHEMA_JSON_SCHEMA_INVALID` diagnostics.

Delete and restore document events are lifecycle events. They do not change the
JSON snapshot patch stream, so their `patch`, `inverse_patch`, and
`changed_paths` are empty while root `before_values` and `after_values` retain
the current JSON snapshot for audit context.

## Comments

- `POST /documents/{document_id}/comment-threads`
- `GET /documents/{document_id}/comment-threads`
- `POST /comment-threads/{thread_id}/comments`
- `POST /comment-threads/{thread_id}/resolve`
- `POST /comment-threads/{thread_id}/reopen`

See `docs/COMMENTS_BASELINE.md`.

## Reviews

- `POST /projects/{project_id}/review-requests`
- `GET /projects/{project_id}/review-requests`
- `GET /review-requests/{review_request_id}`
- `POST /review-requests/{review_request_id}/approve`
- `POST /review-requests/{review_request_id}/request-changes`
- `POST /review-requests/{review_request_id}/comment`
- `POST /review-requests/{review_request_id}/apply`

See `docs/REVIEW_BASELINE.md` and `docs/TASK_005_HARDENING.md`.
See `docs/TASK_046_PLAN.md` for malformed persisted review proposal JSON
diagnostics.

## Core Invariant

Accepted document mutations must create append-only `document_events`.
Replaying those events must reconstruct `json_documents.current_snapshot_json`
exactly.
