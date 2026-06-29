# TASK_100_PLAN.md

## Objective

Add a ZIP JSON import foundation for existing team JSON repositories.

The goal is not Git import/export and not realtime collaboration. The goal is
to let a user upload a ZIP archive, preview its JSON folder structure and simple
JSON-file references, then explicitly apply the import through the existing
versioned document/event model.

## Scope

- Add a read-only ZIP import preview API.
- Add an explicit ZIP import apply API.
- Preserve each ZIP member path as `json_documents.full_path`.
- Parse only `.json` files as import candidates.
- Skip non-JSON files in preview output.
- Validate JSON syntax and root object/array policy.
- Detect active document path conflicts before apply.
- Reuse existing schema file_pattern auto-binding rules.
- Validate schema-bound documents before apply.
- Detect simple JSON-file references from string values and `$ref` fields.
- Create each imported JSON file as a normal document with a `create`
  `document_events` row.
- Apply all accepted files in one transaction.

## API

### Preview

```text
POST /projects/{project_id}/imports/zip-preview
Content-Type: application/zip
X-Actor-Id: <actor_id>
```

The request body is the raw ZIP archive bytes.

Preview is read-only. It does not create documents, document events, schemas,
audit rows, or stored import jobs.

### Apply

```text
POST /projects/{project_id}/imports/zip-apply
Content-Type: application/zip
X-Actor-Id: <actor_id>
```

Optional query parameter:

```text
reason=Imported existing team JSON archive
```

Apply reruns the same preview checks inside a write transaction. If any file is
invalid, conflicting, schema-invalid, or ambiguous, the endpoint rejects the
whole archive and writes nothing.

## Reference Detection

MVP reference analysis is intentionally conservative:

- A string value ending in `.json`, or containing `.json#...`, is treated as a
  JSON file reference.
- A string value in a `$ref` property is also inspected.
- Relative references are resolved against the source JSON document directory.
- Reference target status is one of:
  - `in_archive`
  - `existing_document`
  - `missing`
- Missing references are diagnostics in TASK_100. They do not block apply.

The importer does not infer arbitrary ID relationships or build a semantic data
model from domain-specific fields yet.

## Data Model

No new tables are added.

Imported files are stored in the existing tables:

- `json_documents`
- `document_events`

Each imported JSON file becomes a normal document at version `1`, with a normal
append-only `event_type = "create"` event. The replay invariant remains:

```text
Replay(DocumentEvent[0..N]) == json_documents.current_snapshot_json
```

## Excluded

- Realtime collaboration
- WebSocket
- Offline sync
- Git import/export
- Branching
- Pull request workflow
- Merge/conflict auto-resolution
- AI structure inference
- Complex path-level permissions
- Stored import jobs
- Background import workers
- Semantic ID/entity relationship inference
