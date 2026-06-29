# TASK_079_PLAN.md

## Objective

Add a read-only document patch preview API so editors can ask the server to
apply and validate a candidate patch without creating a document event.

## Endpoint

- `POST /documents/{document_id}/patch-preview`

Request:

```json
{
  "base_version": 1,
  "patch": [
    {"op": "replace", "path": "/learning_rate", "value": 0.0005}
  ]
}
```

Response includes:

- document metadata
- `candidate_content`
- `changed_paths`
- `inverse_patch`
- `before_values`
- `after_values`
- schema validation result
- `persisted: false`

## Policy

- Requires the same document write permission as `PATCH /documents/{document_id}`.
- Checks `base_version` against the current version.
- Applies the same patch operation policy as real document updates.
- Reuses canonical document root validation.
- Reuses semantic no-op update rejection.
- Reuses bound schema validation.
- Does not insert `document_events`.
- Does not update `json_documents.current_version`.
- Does not update `json_documents.current_snapshot_json`.
- Does not write audit rows or persist validation results.
- This task does not add realtime collaboration, UI, Git integration,
  branching, pull requests, AI, offline sync, schema mutation endpoints, or
  complex path-level permissions.

## Verification

- Add service-level preview success coverage.
- Add HTTP preview success coverage.
- Add conflict/no-op preview rejection coverage.
- Add schema-invalid preview rejection coverage.
- Run foundation, schema, replay/integrity, and full test suites.
