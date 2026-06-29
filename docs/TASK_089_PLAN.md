# TASK_089_PLAN.md

## Objective

Add a raw JSON editor save contract that accepts a full candidate JSON document
and converts it into auditable JSON Patch operations before persistence.

## Scope

- `POST /documents/{document_id}/content-preview`
- `PUT /documents/{document_id}/content`
- Server-side recursive diff from current snapshot to candidate content.
- Generated `add`, `remove`, and `replace` patch operations stored through the
  existing update event pipeline.
- Tests for generated patch preview, accepted save, conflicts, invalid content,
  schema validation, API token scope, and replay consistency.

## Policy

- This is not a whole-document overwrite path. The accepted mutation still
  creates one append-only `document_events` row with generated patch,
  inverse patch, before values, after values, and changed paths.
- Candidate content must be canonical JSON object or array.
- `base_version` is mandatory and uses the same `VERSION_CONFLICT` policy as
  patch save and patch preview.
- Content preview is read-only and must not create events, update snapshots,
  increment versions, write audit rows, or persist validation results.
- Schema-bound documents validate the candidate snapshot before any event or
  snapshot write.
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, automatic
  merge/conflict resolution, or complex path-level permissions.

## Verification

- Preview returns `generated_patch`, changed paths, inverse patch, candidate
  content, and validation without mutation.
- Accepted content save stores the generated patch as an `update` event and
  advances the version by exactly one.
- No-op, stale base version, invalid canonical content, and schema-invalid
  candidate content fail without partial writes.
- Replay after content save reconstructs `json_documents.current_snapshot_json`
  exactly.
