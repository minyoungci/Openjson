# TASK_075_PLAN.md

## Objective

Harden coverage for schema-bound restore when the bound `schemas.schema_json`
row is malformed.

## Problem

Patch, rollback, and validate-document already had explicit coverage for
malformed persisted schema JSON. Restore also runs schema validation before
clearing `deleted_at` and inserting the restore event, but that atomicity
boundary was not directly tested.

## Policy

- Restore is a schema-gated mutation for schema-bound documents.
- If loading the bound schema JSON fails, restore returns the structured
  `SCHEMA_JSON_DECODE_FAILED` diagnostic through `INTERNAL_ERROR`.
- The deleted document must remain deleted.
- No restore event, version increment, or snapshot change may be written.
- No schema update/deactivate endpoint, realtime collaboration, UI, Git
  integration, branching, pull request, AI, offline sync, or complex
  path-level permission scope is introduced.

## Verification

- Add a service-level test that binds a document to malformed schema JSON,
  deletes the document, attempts restore, and verifies the row and event count
  are unchanged.
- Run related schema/document tests and the full test suite.
