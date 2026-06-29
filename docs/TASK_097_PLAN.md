# TASK_097_PLAN.md

## Objective

Harden the local non-realtime editor shell so it behaves more like a shareable
JSON document workspace.

This task improves browser-only UX around:

- shareable project/document URLs,
- JSON file import into create/edit buffers,
- stale-version conflict recovery controls.

## Explicit Non-Scope

This task does not implement realtime collaboration, WebSocket, presence,
offline sync, merge/conflict auto-resolution, Git integration, branching, pull
requests, AI features, full authentication, invitation flow, or complex
path-level permissions.

## UI Behavior

The local editor shell accepts URL query parameters:

- `project_id`
- `document_id`
- `actor_id`
- `path_prefix`
- `q`

The generated share URL intentionally excludes API tokens. Recipients still use
their own local actor id or project-scoped bearer token.

JSON file import is browser-local. It reads a selected `.json` file into the
create or editor text buffer. The file contents are not persisted until the user
uses the existing create or save action.

Conflict recovery remains non-realtime:

- stale saves still receive `VERSION_CONFLICT`;
- the UI calls the existing read-only content conflict preview endpoint;
- the user can reload the latest version;
- the user can keep the local buffer against the latest loaded base version and
  then explicitly preview/save again.

## Persistence Boundary

No new database tables or backend mutation endpoints are introduced. Accepted
saves still go through `PUT /documents/{document_id}/content`, which generates
JSON Patch operations and persists normal append-only `document_events` update
rows. Syntax-invalid or unsaved imported JSON remains local and must never
become the canonical latest snapshot.

## Verification

- Static UI tests assert the share/import/conflict recovery assets are served.
- Browser smoke verifies URL hydration, import buffer handling, preview/save,
  and replay consistency after accepted UI save.
- Existing shared-edit HTTP smoke remains green.

