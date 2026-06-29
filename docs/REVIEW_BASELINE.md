# Review Baseline

This document records the approved TASK_005 JSON-native review workflow.

TASK_005 is not a Git pull request workflow. It does not add Git integration,
branching, pull request cloning, realtime review, UI, AI reviewer, WebSocket,
offline sync, automatic merge/conflict resolution, or complex path-level
permissions.

## Model

Review requests store proposed JSON Patch changes before they become canonical.

Tables:

- `review_requests`
- `review_request_changes`
- `review_decisions`

`review_decisions` rows are append-only. Review request status can change.
`review_request_changes` rows are immutable once created.

## Statuses

- `open`
- `changes_requested`
- `approved`
- `applied`
- `closed`

New review requests start as `open`.

## Decisions

- `approve`
- `request_changes`
- `comment`

`comment` is comment-only review feedback and does not change review status.

The review author cannot approve their own review request. Approval must come
from another actor with review decision permission.

After a review request is `applied` or `closed`, later approve,
request-changes, and comment decisions are rejected.

## Apply Semantics

Proposed patches are not canonical until `apply`.

Apply:

- requires review status `approved`
- requires project-level apply permission
- requires document write permission
- checks stored `base_version`
- applies normal JSON Patch operations
- validates schema-bound target snapshots
- creates normal append-only `document_events`
- updates latest snapshots
- marks the review request `applied`

Document mutation and review status update happen in one transaction. If any
change fails, all apply writes are rolled back.

## API

- `POST /projects/{project_id}/review-requests`
- `GET /projects/{project_id}/review-requests`
- `GET /review-requests/{review_request_id}`
- `POST /review-requests/{review_request_id}/approve`
- `POST /review-requests/{review_request_id}/request-changes`
- `POST /review-requests/{review_request_id}/comment`
- `POST /review-requests/{review_request_id}/apply`

All endpoints require `X-Actor-Id`.

## RBAC

- `owner`, `admin`: create, decide, apply, read
- `editor`: create, apply, read
- `reviewer`: decide, read
- `viewer`: read

Apply also requires document write permission.

## Integrity

These operations do not mutate documents and do not create `document_events`:

- create review request
- approve
- request changes
- comment

Only apply mutates documents, and only through the existing versioned document
event pipeline.

Review proposal rows are protected by DB triggers:

- `trg_review_request_changes_no_update`
- `trg_review_request_changes_no_delete`

The core invariant remains:

```text
Replay(DocumentEvent[0..N]) == json_documents.current_snapshot_json
```

## Known Limitations

- No review close endpoint yet.
- No review-specific comment thread anchors yet.
- One proposed change per document per review request in TASK_005.
- No branch, pull request, or automatic merge model.

See `docs/TASK_005_HARDENING.md` for the review hardening policy.
