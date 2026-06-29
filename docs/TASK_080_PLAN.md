# TASK_080_PLAN.md

## Objective

Pin down project-scoped API token behavior for the document patch preview API.

## Scope

- `POST /documents/{document_id}/patch-preview`

## Policy

- Bearer-token requests to patch preview use the token owner as the actor.
- Tokens may preview patches only for documents in the token's project.
- Tokens cannot preview patches for documents in another project.
- Patch preview requires the same document write permission as accepted patch
  mutations.
- Successful preview does not insert `document_events`.
- Successful preview does not update `json_documents.current_version`.
- Successful preview does not update `json_documents.current_snapshot_json`.
- Failed project-scope checks do not mutate either the requested document or
  the token project's documents.
- This task does not add realtime collaboration, UI, Git integration,
  branching, pull requests, AI, offline sync, schema mutation endpoints, or
  complex path-level permissions.

## Verification

- Add bearer-token patch preview coverage for a same-project document.
- Add bearer-token patch preview denial coverage for another project's
  document.
- Verify preview leaves event logs and snapshots unchanged.
- Run API token, foundation, and full test suites.
