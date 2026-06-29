# TASK_074_PLAN.md

## Objective

Lock down the boundary between inactive schema rows and existing document
bindings.

## Policy

- TASK_073 rejects new document creation when an explicit `schema_id` points to
  an inactive schema.
- TASK_074 preserves existing document bindings: a document that already has
  `json_documents.schema_id` continues to validate against that schema even if
  the schema row is inactive.
- Mutation validation must still run before event insertion and snapshot
  updates.
- Failed validation must leave no partial document event, snapshot, version, or
  restore state change.
- No schema update/deactivate endpoint is added in this task.

## Implementation

- Add a document-binding schema loader whose name makes the historical binding
  policy explicit.
- Use that loader for schema-bound patch candidate validation, patch, restore,
  rollback, and validate-document flows.
- Add a legacy inactive-bound document test that verifies validate, invalid
  patch rejection, valid patch, rollback, delete, restore, event
  `validation_schema_id`, and replay consistency.

## Verification

- Related schema and document tests must pass.
- The full test suite must pass.
- No realtime collaboration, UI, Git integration, branching, pull request, AI,
  offline sync, or complex path-level permission scope is introduced.
