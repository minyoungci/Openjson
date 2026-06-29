# TASK_073_PLAN.md

## Objective

Harden document creation so explicit `schema_id` binding cannot attach a new
document to an inactive schema row.

## Problem

Automatic `file_pattern` binding already searches only active schemas. Explicit
`schema_id` binding loaded the schema by ID and checked only project ownership.
If a future migration or deactivation flow leaves `schemas.is_active = 0`, a
client could still bind new canonical documents to that inactive schema by ID.

## Policy

- `schemas` remain immutable.
- TASK_073 does not add a deactivate endpoint or schema update endpoint.
- Automatic schema matching continues to use only active schemas.
- Explicit `schema_id` document creation also requires an active schema.
- Existing documents that already reference a schema keep their historical
  schema binding.
- Rejection happens before document insert and before document event insert.

## Error

Inactive explicit schema binding returns:

```json
{
  "error": {
    "code": "SCHEMA_NOT_ACTIVE",
    "message": "Schema is not active and cannot be bound to new documents.",
    "details": {
      "schema_id": "schema_..."
    }
  }
}
```

## Verification

- Service-level document creation with inactive explicit `schema_id` is
  rejected without `json_documents` or `document_events` writes.
- HTTP document creation returns the structured error and leaves no partial
  writes.
- Related schema tests and the full test suite must pass.
