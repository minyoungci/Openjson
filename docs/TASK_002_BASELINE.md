# TASK_002 Baseline

This document records the approved TASK_002 implementation policy after TASK_002_HARDENING.

TASK_002 adds JSON Schema validation and a project-scoped schema registry. It does not add realtime collaboration, comments, review workflow, Git integration, AI features, branching, pull requests, UI, WebSocket, offline sync, merge/conflict auto-resolution, or complex path-level permission.

## JSON Schema Policy

- JSON Schema draft: Draft 2020-12
- Validator: `jsonschema.Draft202012Validator`
- Schema document validation: `Draft202012Validator.check_schema(schema_json)`
- `format` validation is not enforced in TASK_002.
- TASK_002 focuses on structural validation such as `type`, `required`, `properties`, `enum`, `minimum`, `maximum`, and `additionalProperties`.

## Schema Registry Policy

- Schema rows are immutable and insert-only.
- TASK_002 has no schema update API.
- TASK_002 has no schema deactivate API.
- `schemas.is_active` exists only for future version selection or deactivation policy.
- DB triggers reject direct `UPDATE` and `DELETE` against `schemas`.

## Schema Binding Policy

Document create binding priority:

1. Explicit request `schema_id`.
2. Active schema `file_pattern` match within the same project.
3. No match creates an unbound document.
4. One match creates an automatically bound document.
5. Multiple matches return `AMBIGUOUS_SCHEMA_MATCH`.

Explicit `schema_id` takes precedence over `file_pattern`.

`file_pattern` matching uses Python `fnmatch.fnmatch(full_path, pattern)`.

## Path Policy

Document `full_path` uses POSIX-style `/` separators only.

Backslash `\` in `full_path` is rejected. Backslash in schema `file_pattern` is also rejected so matching behavior is not dependent on OS path separators.

With Python `fnmatch`, `config/*.json` matches `config/model.json`. It also matches nested paths such as `config/nested/model.json`; TASK_002 intentionally does not implement complex glob priority or recursive-depth semantics.

## Validation Write Policy

Schema validation must happen before event insert.

On schema validation failure:

- no document event is inserted
- snapshot is not changed
- version is not incremented

This applies to create, patch, and rollback.

## Rollback Policy

Rollback reconstructs the target version snapshot from events. If the document has a schema binding, the target snapshot must pass that schema before a rollback event is created.

## Validation API Policy

`POST /documents/{document_id}/validate` validates the current snapshot against the bound schema.

For unbound documents, validation returns:

- `valid=true`
- `schema_id=null`
- a warning explaining that the document has no schema binding

## Validation Error Path Policy

Schema validation errors return JSON Pointer paths:

- root: `""`
- nested: `/model/name`
- array item: `/items/0/name`
- slash escaped as `~1`, for example `/a~1b`
- tilde escaped as `~0`, for example `/c~0d`

## Event Audit Policy

`document_events.validation_schema_id` records the schema used to validate an accepted create, patch, or rollback event.

- schema-bound create/patch/rollback events store the schema id
- unbound events store null
- validation failures create no event
- delete events do not perform schema validation and store null

History responses include `validation_schema_id`.

## TASK_001 Invariants

TASK_002 must preserve all TASK_001 invariants:

- latest snapshot plus append-only event log remains the source-of-truth model
- every accepted mutation is attributable and versioned
- rollback is a new event, not history deletion
- soft-deleted documents retain history
- replaying document events reconstructs `json_documents.current_snapshot_json` exactly
