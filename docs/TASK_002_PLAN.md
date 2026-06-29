# TASK_002 Plan: JSON Schema Validation and Schema Registry

TASK_002 adds JSON Schema validation and a project-scoped schema registry on top of the approved TASK_001 foundation.

Do not implement realtime collaboration, comments, review workflow, Git integration, AI features, branching, pull requests, UI, WebSocket, offline sync, merge/conflict auto-resolution, or complex path-level permission in TASK_002.

## JSON Schema Draft Policy

TASK_002 uses JSON Schema Draft 2020-12.

Implementation policy:

- use `jsonschema.Draft202012Validator`
- validate schema documents with `Draft202012Validator.check_schema(schema_json)`
- return `INVALID_JSON_SCHEMA` when a schema document is invalid
- do not enforce `format` validation in TASK_002
- leave `FormatChecker` support as a future open issue

TASK_002 focuses on structural validation such as `type`, `required`, `properties`, `enum`, `minimum`, `maximum`, and `additionalProperties`.

## Dependency Policy

Dependencies are recorded in `requirements.txt` with exact pins from the current local environment for reproducible MVP execution.

## DB Schema Changes

Add `schemas` table:

- `id TEXT PRIMARY KEY`
- `project_id TEXT NOT NULL REFERENCES projects(id)`
- `name TEXT NOT NULL`
- `version TEXT NOT NULL`
- `schema_json TEXT NOT NULL`
- `file_pattern TEXT NULL`
- `is_active INTEGER NOT NULL DEFAULT 1`
- `created_by TEXT NOT NULL REFERENCES users(id)`
- `created_at TEXT NOT NULL`
- `UNIQUE(project_id, name, version)`

Add nullable binding field to `json_documents`:

- `schema_id TEXT NULL REFERENCES schemas(id)`

Schema rows are immutable in TASK_002. Do not add schema update or deactivate APIs.

## Schema Binding Policy

Document create schema binding priority:

1. If request includes `schema_id`, use that schema.
2. Otherwise, find active schemas in the same project where `file_pattern` matches document `full_path`.
3. If 0 schemas match, create an unbound document.
4. If 1 schema matches, automatically bind it.
5. If 2 or more schemas match, return `AMBIGUOUS_SCHEMA_MATCH`.

Matching uses Python `fnmatch.fnmatch` against the document `full_path`.

Do not implement complex file pattern priority in TASK_002.

## Validation Flow

Document create:

1. actor check
2. project check
3. schema resolution
4. object/array root check
5. schema validation if bound
6. document insert and create event insert

Document patch:

1. actor check
2. active document lookup
3. base version check
4. patch apply to candidate snapshot
5. schema validation if document has `schema_id`
6. event insert and snapshot update

Rollback:

1. actor check
2. active document lookup
3. base version check
4. reconstruct target version snapshot
5. schema validation if document has `schema_id`
6. rollback event insert and snapshot update

Schema validation must happen before event insert. On schema validation failure, do not insert events, do not update snapshots, and do not increment versions.

## API Endpoints

- `POST /projects/{project_id}/schemas`
- `GET /projects/{project_id}/schemas`
- `GET /schemas/{schema_id}`
- `POST /documents/{document_id}/validate`

Existing document create accepts optional `schema_id`.

## Error Codes

TASK_002 adds:

- `SCHEMA_NOT_FOUND`
- `INVALID_JSON_SCHEMA`
- `SCHEMA_VALIDATION_FAILED`
- `AMBIGUOUS_SCHEMA_MATCH`
- `SCHEMA_PROJECT_MISMATCH`
- `DOCUMENT_HAS_NO_SCHEMA`

## Validation Error Format

Schema validation errors use JSON Pointer paths.

Examples:

- root: `""`
- nested: `/model/name`
- array item: `/items/0/name`
- escaped slash: `/a~1b`
- escaped tilde: `/c~0d`

Error response:

```json
{
  "error": {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "Document failed schema validation.",
    "details": {
      "errors": [
        {
          "path": "/learning_rate",
          "message": "0.001 is less than the minimum of 0.01",
          "validator": "minimum",
          "expected": 0.01,
          "actual": 0.001
        }
      ]
    }
  }
}
```

## Test Plan

Schema registry:

- valid schema create
- invalid JSON Schema reject
- missing project reject
- missing actor reject
- schema list
- schema get

Schema binding:

- explicit `schema_id` success
- explicit `schema_id` invalid content reject
- no document/event on validation failure
- cross-project schema reject
- file pattern auto binding success
- no file pattern match creates unbound document
- multiple file pattern match returns `AMBIGUOUS_SCHEMA_MATCH`

Patch validation:

- schema-valid patch succeeds
- schema-invalid patch rejects
- invalid patch does not increment version, insert event, or change snapshot

Rollback validation:

- schema-valid rollback succeeds
- schema-invalid rollback rejects
- invalid rollback does not insert event or change snapshot

Validation API:

- bound schema document valid
- bound schema document invalid
- unbound document returns valid with warning

Regression:

- all existing TASK_001 tests continue to pass
- replay consistency invariant remains intact
- diff API behavior remains intact
