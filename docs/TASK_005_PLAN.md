# TASK_005 Plan: JSON-Native Review Workflow

TASK_005 adds a minimal backend review workflow for proposed JSON Patch changes.

This is not a Git branch or pull request clone. It does not add Git integration,
branching, pull requests, realtime review, UI, AI reviewer, WebSocket, offline
sync, automatic merge/conflict resolution, or complex path-level permissions.

## Scope

- Add `review_requests` table.
- Add `review_request_changes` table.
- Add append-only `review_decisions` table.
- Store proposed patch sets before canonical apply.
- Support approve, request changes, and comment-only decisions.
- Apply approved changes through the existing document patch pipeline.
- Preserve schema validation, base version checks, event logging, and replay
  consistency.

## DB Changes

`review_requests`:

- `id`
- `project_id`
- `author_id`
- `status`: `open`, `changes_requested`, `approved`, `applied`, `closed`
- `title`
- `description`
- `created_at`
- `updated_at`
- `applied_by`
- `applied_at`

`review_request_changes`:

- `id`
- `review_request_id`
- `document_id`
- `base_version`
- `patch`
- `changed_paths`
- `reason`
- `created_at`

`review_decisions`:

- `id`
- `review_request_id`
- `actor_id`
- `decision_type`: `approve`, `request_changes`, `comment`
- `body`
- `created_at`

`review_decisions` is append-only at the DB level.

## Status Policy

- New review requests start as `open`.
- `approve` moves `open` or `changes_requested` to `approved`.
- `request_changes` moves `open` or `approved` to `changes_requested`.
- `comment` records an append-only decision and does not change status.
- `apply` is allowed only from `approved` and moves status to `applied`.

## Apply Policy

Review apply is a controlled call into the existing document patch pipeline.

Apply must:

- require `REVIEW_APPLY` and document write permission
- check each target document is active and in the same project
- check each stored `base_version` still matches the document version
- apply JSON Patch using the existing patch/inverse-patch logic
- run schema validation for schema-bound documents
- insert normal `document_events`
- update snapshots and review status in the same transaction

If any change in a multi-document review fails, the entire apply transaction is
rolled back.

## API Endpoints

- `POST /projects/{project_id}/review-requests`
- `GET /projects/{project_id}/review-requests`
- `GET /review-requests/{review_request_id}`
- `POST /review-requests/{review_request_id}/approve`
- `POST /review-requests/{review_request_id}/request-changes`
- `POST /review-requests/{review_request_id}/comment`
- `POST /review-requests/{review_request_id}/apply`

All endpoints require `X-Actor-Id`.

## RBAC Policy

- `owner`, `admin`: create, decide, apply, read
- `editor`: create, apply, read
- `reviewer`: decide, read
- `viewer`: read only

Canonical apply still requires document write permission.

## Integrity Policy

Creating, approving, requesting changes, and commenting on a review request must
not mutate JSON documents or create `document_events`.

Only `apply` can mutate canonical documents, and it must do so via normal
versioned `document_events`.

The replay invariant remains:

```text
Replay(DocumentEvent[0..N]) == json_documents.current_snapshot_json
```

## Test Plan

- create review request records proposed patch without document mutation
- approve then apply creates normal document event
- apply requires approval
- reviewer can approve but cannot apply
- editor can create/apply but cannot approve
- request changes blocks apply until reapproved
- comment-only decision does not change status or document
- schema-invalid proposed change is rejected without review/event
- version conflict during apply leaves review approved and rolls back all apply writes
- review decisions reject direct SQL update/delete
- review routes are registered
- existing replay consistency tests continue to pass
