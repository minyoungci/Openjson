# TASK_092_PLAN.md

## Objective

Add a read-only raw-content conflict preview API for non-realtime shared JSON
editing.

## Scope

- Add `POST /documents/{document_id}/content-conflict-preview`.
- Accept `base_version` plus exactly one of `content` or `content_text`.
- Reconstruct the client's base snapshot from `document_events`.
- Compare base-to-candidate changes with base-to-current server changes.
- Return changed paths, before/after values, generated patches, and conflict
  details.

## Policy

- This endpoint is read-only. It does not create `document_events`, update
  `json_documents`, increment versions, write audit rows, or persist
  validation state.
- It requires the same document write permission as content preview/save
  because it previews a candidate mutation.
- It intentionally allows stale `base_version` values that refer to an existing
  document version.
- Future or non-positive base versions fail with `INVALID_VERSION_RANGE`.
- Candidate JSON is still parsed, normalized, constrained to root object/array,
  and validated against the bound schema before a conflict result is returned.
- If replaying the event log to the latest version does not match the latest
  snapshot, the endpoint fails instead of hiding an invariant violation.
- Path conflicts include exact JSON Pointer matches and ancestor/descendant
  overlaps.
- This task does not add realtime collaboration, WebSocket, UI, Git
  integration, branching, pull requests, AI features, offline sync, automatic
  merge/conflict resolution, or complex path-level permissions.

## Response Shape

The response includes:

- `base_content` and `base_content_text`
- `current_content` and `current_content_text`
- `candidate_content` and `candidate_content_text`
- `client_changes`
- `server_changes`
- `client_generated_patch`
- `server_generated_patch`
- `conflicting_paths`
- `conflicts`
- `has_conflicts`
- `latest_event`
- `validation`
- `persisted = false`

## Verification

- Stale client/server changes are compared from the same replayed base
  snapshot.
- Exact path conflicts are reported.
- Ancestor/descendant path conflicts are reported.
- Non-overlapping stale changes return `has_conflicts = false`.
- Schema-invalid candidates are rejected without partial writes.
- Malformed `content_text` is rejected without partial writes.
- The HTTP shared-edit smoke flow exercises the endpoint.
