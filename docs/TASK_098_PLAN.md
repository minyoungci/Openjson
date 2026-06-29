# TASK_098_PLAN.md

## Objective

Make the local non-realtime editor shell schema-aware enough for real JSON
document entry and validation workflows.

This task improves browser-only UX around:

- displaying the selected document's bound schema metadata,
- showing create-time schema match status for a new document path,
- allowing explicit schema binding during document creation when the actor has
  access to project schemas.

## Explicit Non-Scope

This task does not implement realtime collaboration, WebSocket, presence,
offline sync, merge/conflict auto-resolution, Git integration, branching, pull
requests, AI features, full authentication, invitation flow, schema update or
deactivation APIs, or complex path-level permissions.

## UI Behavior

The local editor shell loads project schemas from:

```text
GET /projects/{project_id}/schemas
```

When the selected document has a bound schema, the inspector renders schema
name, version, activity status, file pattern, and any persisted schema JSON
diagnostic already returned by the editor-state API.

When the create panel is open and a full path is entered, the UI previews
automatic schema binding with:

```text
GET /projects/{project_id}/schema-matches?full_path=<path>
```

The preview is read-only. It does not create schemas, documents, document
events, audit rows, or validation state.

If the user chooses a schema explicitly in the create panel, document creation
sends `schema_id` to the existing create document API. If no schema is selected,
the backend keeps its existing automatic file-pattern binding behavior.

## Persistence Boundary

No database schema changes are introduced. Accepted document creation still
goes through:

```text
POST /projects/{project_id}/documents
```

The backend remains the only source of truth for schema binding and validation.
The UI preview is only advisory and may be stale by the time creation is
submitted.

## Verification

- Static UI tests assert schema inspector, schema selector, schema match preview
  assets, and schema API references are served.
- Browser smoke should verify schema metadata rendering and create-time schema
  match preview when a project has a matching active schema.
- Existing full test suite must remain green.
