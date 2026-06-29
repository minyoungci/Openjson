# TASK_005 Hardening

This document records the TASK_005 review workflow hardening policy.

TASK_005_HARDENING does not add realtime collaboration, Git integration,
branching, pull requests, AI review, WebSocket, offline sync, UI work,
automatic merge/conflict resolution, or complex path-level permissions.

## Scope

- Keep review requests JSON-native and patch-based.
- Preserve the rule that review metadata does not mutate canonical documents.
- Harden review proposal immutability.
- Require separation between review author and approver.
- Treat applied and closed review requests as terminal for later decisions.
- Keep review apply routed through the existing document event pipeline.

## Proposal Immutability

`review_request_changes` rows store the proposed JSON Patch set reviewed by
reviewers. They are immutable at the DB level.

SQLite triggers reject direct updates and deletes:

- `trg_review_request_changes_no_update`
- `trg_review_request_changes_no_delete`

Review request status can still change through service APIs.

## Approval Policy

The review author cannot approve their own review request.

This keeps the minimal review workflow from becoming a self-approval shortcut.
Owners and admins still have broad project capability, but review approval must
come from another actor with `REVIEW_DECIDE`.

## Terminal State Policy

Once a review request is `applied` or `closed`, no further review decisions are
accepted.

The current API has no close endpoint yet, but `closed` is treated as terminal
for forward compatibility.

## Failure Policy

Failed review creation or decision attempts must not leave partial metadata.

Examples:

- stale `base_version` during review creation creates no review request
- schema-invalid proposed patch creates no review request
- self-approval creates no decision row and leaves status unchanged
- decisions after apply create no decision row and leave status unchanged

Failed review apply still rolls back all document events, snapshot updates, and
review status updates in the same transaction.

## Dev Seed Policy

The dev seed keeps `user_dev` as the owner actor and now also creates:

- `user_dev_editor`
- `user_dev_reviewer`
- `user_dev_viewer`

This allows local Swagger smoke tests to exercise review create, approve, apply,
and read flows without disabling the self-approval rule.

## Tests

Hardening tests cover:

- author self-approval rejection
- no decision row after failed self-approval
- applied review rejects later approve/request-changes/comment decisions
- stale proposal `base_version` creates no review request
- review proposal rows are immutable at the DB level
- migration idempotence includes review hardening triggers
- dev seed creates owner/editor/reviewer/viewer actors

The core replay invariant remains unchanged:

```text
Replay(DocumentEvent[0..N]) == json_documents.current_snapshot_json
```
