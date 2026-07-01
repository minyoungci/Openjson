# DATA_MODEL.md

This document is the standard data-model entrypoint for the current backend
implementation.

The canonical product direction remains:

```text
Latest JSON snapshot is for fast access.
Append-only event log is for trust, audit, diff, blame, and rollback.
```

## Current Storage

The current local MVP uses SQLite.

`PRAGMA foreign_keys = ON` is enabled for managed connections.

PostgreSQL/JSONB remains a future production migration topic and is not part of
the current implementation.

## Tables

- `users`
- `user_credentials`
- `user_sessions`
- `refresh_tokens`
- `schema_migrations`
- `api_tokens`
- `workspaces`
- `projects`
- `project_members`
- `project_invitations`
- `email_deliveries`
- `oidc_states`
- `oidc_identities`
- `offline_sync_operations`
- `json_documents`
- `document_events`
- `document_snapshots`
- `editor_presence`
- `schemas`
- `comment_threads`
- `comments`
- `review_requests`
- `review_request_changes`
- `review_decisions`
- `audit_log`

## Key Constraints

- `users.email` is unique.
- `user_credentials.user_id` is unique and references `users(id)`.
- `user_sessions.token_hash` is unique.
- `refresh_tokens.token_hash` is unique.
- `api_tokens.token_hash` is unique.
- `project_members(project_id, user_id)` is unique.
- `project_members(project_id, role)` is indexed for owner protection checks.
- `project_invitations.token_hash` is unique.
- `project_invitations.project_id` references `projects(id)`.
- `project_invitations.invited_by` and `accepted_by` reference `users(id)`.
- `oidc_identities(issuer, subject)` is unique.
- `offline_sync_operations(actor_id, client_operation_id)` is unique.
- `schemas(project_id, name, version)` is unique.
- `json_documents(project_id, full_path)` is unique for non-deleted documents
  through a partial unique index.
- `document_events(document_id, result_version)` is unique.
- `document_snapshots(document_id, version)` is unique.
- `document_snapshots.source_event_id` is unique and references
  `document_events(id)`.
- `editor_presence(document_id, actor_id)` is unique.
- `review_request_changes(review_request_id, document_id)` is unique.
- `audit_log(project_id, created_at, id)` is indexed for project-scoped reads.
- `audit_log(actor_id, created_at, id)` is indexed for future actor-scoped
  investigation.

## Append-Only and Immutable Tables

Append-only or immutable behavior is enforced with SQLite triggers:

- `document_events`: no update, no delete
- `document_snapshots`: no update, no delete
- `schemas`: no update, no delete
- `comments`: no update, no delete
- `review_decisions`: no update, no delete
- `review_request_changes`: no update, no delete
- `audit_log`: no update, no delete
- `schema_migrations`: no update, no delete

Project owner protection is also enforced with SQLite triggers:

- `trg_project_members_keep_owner_update`
- `trg_project_members_keep_owner_delete`

## Document Model

`json_documents` stores the latest canonical snapshot and current version.

`json_documents.full_path` is accepted only as a relative POSIX-style path. It
must not be absolute, contain Windows separators, contain empty path segments,
end with `/`, or use `.` / `..` segments.

`document_events` stores every accepted create, update, delete, restore, and
rollback event. Every accepted document mutation must update both the event log
and latest snapshot in one transaction.
Accepted document mutation responses expose the created event metadata
(`event_id` and `event_type`) so non-realtime editor clients can correlate a
successful save with the immutable `document_events` row. Failed mutation
attempts, including version conflicts, do not create event rows and therefore do
not produce accepted event metadata.
Version conflict diagnostics may include the latest accepted event metadata for
client recovery, but that metadata is read from the existing append-only
`document_events` table and is not itself a new event or mutation.
Accepted update patches must produce a latest snapshot different from the
previous snapshot; semantic no-op update patches are rejected before event or
snapshot writes.
The document patch preview API runs the same candidate patch and validation
pipeline as accepted updates but is read-only; it does not create
`document_events`, update latest snapshots, write audit rows, or persist
validation results. Because it previews a candidate mutation, it uses the same
document write permission and active-document lifecycle boundary as accepted
patch mutations. Soft-deleted documents are not previewable, and malformed
persisted latest snapshots fail with structured `SNAPSHOT_JSON_DECODE_FAILED`
diagnostics before any candidate result is returned.
The raw JSON editor content APIs are thin adapters over the same event model.
They accept a full candidate JSON object or array, generate recursive
path-level patch operations from the current snapshot, and persist accepted
saves as ordinary `update` events. They do not overwrite snapshots without an
event, and content preview is read-only.
Raw editor requests may submit `content_text`; this text is parsed before
canonical validation and patch generation. Malformed text is rejected before
event insert or snapshot update, so invalid JSON text is never stored as the
latest canonical snapshot.
The raw-content conflict preview API is a read-only diagnostic over the same
document snapshot/event model. It reconstructs the requested base version from
`document_events`, verifies the replayed latest state matches
`json_documents.current_snapshot_json`, compares base-to-candidate and
base-to-current changes, and reports JSON Pointer overlaps without creating
events, updating snapshots, incrementing versions, writing audit rows, or
persisting validation state.
Rollback targets must be older than the request `base_version`; current-version
or future-version targets are rejected before any event or snapshot write.
Delete and restore events represent lifecycle marker changes rather than JSON
content patches. They store empty `patch`, `inverse_patch`, and `changed_paths`
arrays while retaining root `before_values` and `after_values` records for
auditability.

The project document event feed is a read-only API view over `document_events`
joined to `json_documents`; it does not introduce a separate event store.

`document_snapshots` stores immutable compacted snapshots derived from
`document_events`. It is a replay acceleration artifact, not a replacement
source of truth. Snapshot compaction first verifies that replaying the full
event chain to `json_documents.current_version` reconstructs
`json_documents.current_snapshot_json`; if the invariant fails, compaction
writes nothing. Existing compacted snapshots are treated as idempotent only
when their stored JSON and `source_event_id` still match event-log replay.

The document event detail API is a read-only view over one `document_events`
row joined through its `json_documents` parent. Optional before/after snapshots
are reconstructed from the same append-only event log and are not persisted.
Malformed event JSON fields are reported as structured `json_errors` on the
event detail payload; snapshot reconstruction failures are reported under
`snapshots.error`.

Document history and the project document event feed use the same read-only
malformed event JSON diagnostics. Path-history and blame stop replay when an
event JSON field is malformed and return `replay_error` instead of mutating or
repairing the event log.

Replay-dependent version, diff, rollback, and internal replay helper surfaces
fail with a structured `INTERNAL_ERROR` when malformed event JSON prevents
trustworthy reconstruction. Rollback performs no partial mutation in that
state.

Core document read and mutation paths fail with a structured
`SNAPSHOT_JSON_DECODE_FAILED` diagnostic when
`json_documents.current_snapshot_json` is malformed. Mutation paths do not
create events or alter document rows in that state.

The project document search API is a read-only derived view over
`json_documents.current_snapshot_json`; it does not introduce a persistent
search index.
Malformed persisted latest snapshot JSON is reported as partial search
diagnostics on this read-only surface; canonical document reads and mutations
still fail with structured `SNAPSHOT_JSON_DECODE_FAILED` errors.

The project document tree API is a read-only derived view over
`json_documents.full_path`; it does not introduce a persisted folder table.
Project document list and tree `path_prefix` filters use the same relative
POSIX-style path segment policy as canonical document paths.

The project export archive API is also read-only. It derives a JSON archive
from existing project metadata, schemas, latest document snapshots, and
append-only `document_events`; it does not create export rows or files.
Its integrity section includes both replay consistency and event-chain metadata
diagnostics for the exported documents.
Malformed persisted document snapshot or event JSON is exported as structured
document/event parse diagnostics while the archive integrity status is marked
failed.

The project replay integrity API is a read-only diagnostic view over
`json_documents` and `document_events`; it does not repair or mutate data.

The project event-chain integrity API applies the event-chain diagnostic across
project documents. It does not persist integrity results or repair invalid
chains.

The combined database integrity CLI is a read-only operational gate. It
combines replay consistency, event-chain metadata diagnostics,
`PRAGMA foreign_key_check`, `PRAGMA integrity_check`, and schema migration
ledger diagnostics; it does not persist integrity results or repair invalid
data.

Replay and event-chain integrity diagnostics report malformed persisted JSON in
`json_documents.current_snapshot_json` or document event JSON fields as
structured failures instead of treating decoder exceptions as successful
checks.

The document replay integrity API uses the same diagnostic check for one
document. It includes soft-deleted documents and does not persist integrity
results.

The document event-chain integrity API is a stricter read-only diagnostic over
one document's `document_events`. It checks contiguous version metadata and
stored per-event before/after tracking without mutating or repairing data.

The project validation report API is a read-only diagnostic view over
`json_documents`, bound `schemas`, and `document_events`; it does not persist
validation or integrity results.
It uses the same malformed persisted JSON diagnostics as replay and event-chain
integrity checks, returning structured validation/integrity failures instead of
server errors for corrupt snapshot or event JSON fields.

The document validation API is also read-only. It validates the active latest
snapshot and returns document context (`project_id`, `full_path`,
`current_version`, `deleted_at`, and `schema_id`) with the validation result so
clients can associate validation output with the exact snapshot version that was
checked. It does not persist validation rows or create document events.

The document editor-state API is a read-only composite view for active editor
loads. It derives the current snapshot, actor role/capabilities, required base
version, workflow/action metadata, bound schema metadata, optional validation
result, and recent events from existing tables. It does not create
`document_events`, update snapshots, increment versions, write audit rows, or
persist validation state. Soft-deleted documents are intentionally not
editor-loadable through this surface; history and integrity APIs remain
available for deleted document audit workflows.
Its `document.content_text` field is a deterministic pretty JSON projection of
the latest canonical snapshot and is not stored as a separate source of truth.
Its `workflow` field is also derived metadata. It tells editor clients which
existing API actions are available for the actor and documents the
non-realtime save contract; it does not introduce a workflow state table.
The nested `workflow.state_machine` field is likewise derived metadata. It
standardizes client-owned editor states and server-verified outcomes for the
non-realtime editor screen, but no editor state-machine rows are stored.
The project editor bootstrap API is also a read-only derived aggregate. It
combines `projects`, the project document list, the project document tree, and
an optional active document editor-state into one response for first screen
loads. No project editor bootstrap table exists, and this API does not create
`document_events`, update snapshots, increment versions, write audit rows, or
persist validation state.
The local static editor shell introduced in TASK_096 also has no database
tables. It keeps temporary editor text in the browser, and accepted saves still
persist only through the existing content update API and append-only
`document_events`.
TASK_097 share URLs, imported JSON files, and conflict-recovery local buffers
are also browser-only UI state. They do not add tables, alter snapshots, or
write events until the user explicitly creates a document or accepts a content
save through the existing backend APIs.
TASK_098 schema inspector state, project schema lists, and create-time schema
match previews are browser-only projections of existing schema read APIs. They
do not add tables, bind documents, alter schema rows, or write events until the
user explicitly creates a document through the existing document creation API.
TASK_099 schema validation failure rendering is also browser-only. Failed
schema validation responses continue to leave documents, events, snapshots,
versions, audit rows, and validation persistence unchanged.
TASK_100 ZIP import preview is also derived and read-only. It does not persist
import jobs, folder rows, relationship rows, documents, events, audit rows, or
validation state. TASK_100 ZIP import apply writes only existing canonical
document tables: each imported `.json` member becomes one `json_documents` row
and one append-only `document_events` `event_type = "create"` row at version
`1`. The apply endpoint runs all accepted file creates in one transaction, so a
precheck or write failure leaves no partial imported documents or events.
Folder summaries and simple JSON-file reference edges are response projections
computed from the ZIP archive and existing active document paths.
TASK_101 editor presence is transient operational state. It stores active
viewer/editor heartbeat data for one document and one actor, including
`status`, `base_version`, `dirty`, optional `cursor_path`, `opened_at`, and
`last_seen_at`. It may update in place because it is not canonical JSON content
history. Collaboration checkpoints are not a new table; they are read from
accepted append-only `document_events`. Local autosave uses the existing content
save endpoint, so every accepted autosave remains a normal document update
event and must preserve replay consistency.
TASK_102 WebSocket collaboration also adds no database table. WebSocket
connections are in-memory process state unless optional Redis fanout is enabled
through `OPENJSON_REDIS_URL`. Each broadcast payload is still derived from
existing `editor_presence` rows and accepted append-only `document_events`.
TASK_103 adds local password/session and invitation tables:
`user_credentials`, `user_sessions`, and `project_invitations`.
`user_credentials.password_hash` stores PBKDF2 password hashes only.
`user_sessions` stores bearer session token hashes, expiration, last-used, and
revocation timestamps; session rows are operational auth state and not JSON
content history. `project_invitations` stores invitation token hashes,
expiration, role, invited email, accepted user, and accepted timestamp. The
actual invitation token is returned only at creation time. Invitation
acceptance writes `project_members` in the same transaction as marking the
invitation accepted.

TASK_103 safe auto-merge adds no table. It is a mutation-time policy on
`PUT /documents/{document_id}/content` with `merge_strategy = "auto"`. The
server reconstructs the stale base snapshot from `document_events`, verifies
latest replay consistency, rejects overlapping or array-sensitive changes, then
creates a normal append-only `document_events` update against the current
server version. Failed auto-merge attempts leave no event, snapshot, version,
or audit mutation.

TASK_104 transient text collaboration also does not add canonical document
storage. The in-process text session keeps raw editor text, text revision, and
accepted insert/delete/replace operations only as operational WebSocket state.
`text_session.commit` parses that text as JSON and calls the existing content
update pipeline; only the resulting `document_events` update row is durable
document history.

TASK_117 WebSocket message limiting adds no table. It is in-memory
per-connection operational state and does not mutate `editor_presence`,
`document_events`, snapshots, audit rows, or text collaboration sessions.

TASK_118 HTTP request body limiting also adds no table. It is request-time
operational enforcement before endpoint parsing and must reject oversized
requests before document, event, audit, auth, or import mutations occur.

TASK_119 project usage limiting adds no table. It derives active document count
and active latest snapshot bytes from `json_documents` rows where
`deleted_at IS NULL`. It is an operational guard before create, update,
restore, rollback, and ZIP import writes; it does not rewrite historical
`document_events`, account for deleted historical event-log bytes, or implement
billing quotas.

TASK_120 SQLite backup retention adds no table. It is local filesystem
operational state for `scripts/backup_sqlite.py` and does not mutate
`json_documents`, `document_events`, schema migrations, audit rows, or
canonical JSON content.

TASK_123 SQLite backup encryption also adds no table. It encrypts backup files
on disk and records non-secret verification metadata in adjacent backup
manifests. Restore decrypts to temporary local files before running the same
combined database integrity checks. Encryption keys remain external operational
secrets and are never stored in SQLite or backup manifests.

TASK_127 SQLite backup scheduling also adds no table. It is an in-process
background task for the single-instance Render SQLite deployment. It reuses
the existing integrity-checked backup flow and writes backup files plus
manifests to the configured filesystem output directory. Scheduler state is
runtime configuration, not database state.

TASK_128 encrypted scheduled-backup readiness hardening also adds no table. It
derives readiness from runtime backup scheduler configuration and reports only
non-secret status fields. Missing encryption secrets for enabled encrypted
scheduled backups fail `GET /ready` without mutating database rows or backup
files.

TASK_129 SQLite backup status checking also adds no table. It is a read-only
filesystem inspection over backup manifests and backup files. It verifies
latest backup age, manifest JSON, file existence, size, SHA-256, integrity
status, and optional encryption policy without mutating SQLite rows or backup
artifacts.

TASK_130 unexpected internal error response hardening also adds no table. It
changes only HTTP error serialization for catch-all unknown exceptions. Known
`AppError` diagnostics remain structured; unknown exception responses expose a
request id and diagnostic code by default instead of raw exception messages.

TASK_131 WebSocket collaborative text-session permission hardening also adds no
table. `text_session.join` remains a read-permission operation, while
`text_session.op` and `text_session.commit` require document write permission
before mutating transient text-session state or writing a durable
`document_events` update.

TASK_132 WebSocket text-operation idempotency also adds no table. Optional
`client_operation_id` values are kept only in the in-process transient text
session operation list and prevent duplicate `text_session.op` messages from
mutating shared text twice. Durable JSON history remains only the accepted
`document_events` row created by `text_session.commit`.

TASK_133 browser live-text acknowledgement ordering also adds no table. The
static browser UI tracks one pending local `text_session.op` in memory, waits
for `text_session.op.accepted`, and then re-diffs the editor buffer before
sending another operation. This is client-owned transient state and does not
change canonical snapshots or append-only document events.

TASK_134 accepted text-session payload resynchronization also adds no table.
`text_session.op.accepted` includes the in-process session `content_text` so
browser clients can realign transient shadow text after transformed operations
or idempotent replays. This payload is not canonical storage; only a successful
`text_session.commit` creates durable `document_events` history.

TASK_135 browser live-text local-buffer preservation also adds no table. The
static browser UI treats unsent or unacknowledged editor text as client-owned
transient state, preserves that visible buffer when remote accepted operations
arrive, and re-diffs it against the authoritative session shadow after local
acknowledgement. It does not change canonical snapshots, append-only
`document_events`, rollback, replay, or content save contracts.

TASK_136 live-text session-state reconnect preservation also adds no table.
`text_session.state` remains authoritative in-process session data; the static
browser UI preserves dirty or previously pending local editor text when that
state arrives, clears stale pending state, and re-diffs the local buffer against
the authoritative session shadow. Clean buffers still adopt the server session
text. No canonical JSON storage, snapshots, or append-only events are changed
until `text_session.commit` succeeds.

TASK_137 live-text unacknowledged-operation preservation also adds no table.
The static browser UI keeps a transient flag when a local text operation was
sent but the WebSocket closed, errored, or returned an error before
acknowledgement. The flag makes the next authoritative session state preserve
and re-diff the visible local buffer instead of treating the optimistic shadow
as clean. It is cleared after acknowledgement or resync and never becomes
canonical document storage.

TASK_138 stale live-text operation transform hardening also adds no table.
Stale `text_session.op` messages are transformed only when the in-process
single-operation protocol can preserve already accepted text safely. Unsafe
transforms are rejected as `VERSION_CONFLICT` so clients resync transient
session state; no canonical snapshots or append-only `document_events` are
changed until a valid `text_session.commit` succeeds.

TASK_104 adds operational auth and sync tables:

- `refresh_tokens`: hashed one-time refresh tokens linked to a session and
  rotation family.
- `email_deliveries`: invitation email delivery metadata without storing the
  invitation token body.
- `oidc_states`: short-lived OIDC state/nonce rows.
- `oidc_identities`: provider issuer/subject bindings to local users.
- `offline_sync_operations`: idempotency and result records for queued offline
  content-save attempts.

These tables are not canonical JSON content. Successful offline sync items
still create ordinary append-only `document_events` rows through the content
update pipeline; conflict and failed items do not mutate snapshots.

The project activity timeline API is a read-only merged view over
`document_events` and `audit_log`; it does not persist a separate activity
stream.
Malformed persisted `document_events.changed_paths` JSON is reported as
`document_event.json_errors` on project activity reads.
Malformed persisted `audit_log.details` JSON is reported as `details_error` on
audit log, activity, and export reads instead of mutating or repairing the
append-only row.

## Schema Model

`schemas` stores immutable project-scoped JSON Schema Draft 2020-12 documents.

`json_documents.schema_id` is nullable and references `schemas(id)`.

The schema usage API is a read-only diagnostic view over one schema and the
documents currently bound to it; it does not persist validation results or
schema usage rows.
Malformed persisted latest snapshot JSON is reported as a `json_syntax`
validation failure for the affected bound document instead of a server error.

Malformed persisted `schemas.schema_json` is reported as `schema_json_error` on
schema metadata/export reads and as `schema_json_syntax` validation failures on
usage and validation report surfaces. Schema-bound document mutations fail with
structured `SCHEMA_JSON_DECODE_FAILED` diagnostics and no partial writes,
including patch, restore, rollback, and validate-document mutation gates.
Persisted schema rows whose `schema_json` parses as JSON but fails JSON Schema
Draft 2020-12 schema checking are also reported on read-only schema diagnostic
surfaces. Schema metadata includes `schema_json_error.diagnostic_code =
SCHEMA_JSON_SCHEMA_INVALID`; schema usage and project validation report mark
affected documents invalid with `validator = schema_json_invalid`. These
diagnostics do not repair schemas or mutate documents, events, versions,
snapshots, audit rows, or validation state.
Schema-bound document mutation gates treat the same persisted invalid schema
state as an internal data-integrity diagnostic and fail before event insert,
snapshot update, version increment, restore lifecycle update, or validation
state persistence. The structured mutation diagnostic uses
`diagnostic_code = SCHEMA_JSON_SCHEMA_INVALID`.

The schema match preview API is a read-only derived view over active
`schemas.file_pattern` values; it does not bind documents or persist match
rows. It validates `full_path` using the same relative POSIX-style document path
policy used by document creation.

Provided `schemas.file_pattern` values must also be relative POSIX-style glob
patterns. Glob path segments such as `*` and `**` are allowed, but absolute
patterns, Windows separators, empty path segments, trailing `/`, and literal
`.` / `..` segments are rejected before immutable schema rows are inserted.
Schema file_pattern matching is case-sensitive and uses the stored POSIX-style
document `full_path` exactly; it does not use OS-normalized case matching.
New document creation binds only active schemas. Explicit `schema_id` requests
are rejected when the referenced schema row has `is_active = 0`; existing
documents that already reference a schema keep their immutable historical
binding and continue validating mutations against that bound schema.

## Comment Model

`comment_threads` can anchor to a document, JSON Pointer path, or document
event.

`comments` are append-only messages in a thread.

## Review Model

`review_requests` stores review metadata and status.

`review_request_changes` stores immutable proposed JSON Patch changes.

`review_decisions` stores append-only approve, request-changes, and comment
decisions.

Only review apply mutates canonical documents, and it does so through normal
`document_events`.

Malformed persisted `review_request_changes.patch` or `changed_paths` is
reported as `json_errors` on review/export reads. Review apply fails with a
structured `REVIEW_CHANGE_JSON_DECODE_FAILED` diagnostic and no partial
document or review status mutation.

## Project Membership Model

`project_members` stores project-level RBAC roles for existing users.

Allowed roles:

- `owner`
- `admin`
- `editor`
- `reviewer`
- `viewer`

TASK_007 adds member management APIs for this table. Membership changes do not
mutate JSON documents and do not create `document_events`.

Every project must retain at least one owner.

## API Token Model

`api_tokens` stores hashed project-scoped API tokens.

Stored fields include:

- `id`
- `user_id`
- `project_id`
- `name`
- `token_prefix`
- `token_hash`
- `created_at`
- `last_used_at`
- `revoked_at`

Token secrets are returned only once on creation. The database stores only the
hash and short prefix.

API tokens are scoped to one project and still use project RBAC through the
owning user.

## Audit Log Model

`audit_log` stores append-only operational/security events that are not JSON
document mutations.

TASK_008 starts by logging successful and rejected project member
add/update/remove attempts. Document content changes remain in
`document_events`.

The table intentionally stores resource identifiers as text without foreign
keys so rejected attempts involving missing actors or resources can still be
recorded.

Malformed persisted `details` JSON is reported as a read diagnostic and is not
rewritten by read APIs.

## Migration Ledger Model

`schema_migrations` stores the applied SQLite MVP schema baseline IDs.

It is append-only and is used by local/staging migration smoke commands. Legacy
MVP databases receive baseline migration rows after `init_db` brings the schema
to the current shape.

## Core Replay Invariant

For every document:

```text
Replay(DocumentEvent[0..N]) == json_documents.current_snapshot_json
```
