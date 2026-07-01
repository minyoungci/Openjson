# TASK_166 Plan - Guard stale comment action failures and statuses

Goal: prevent delayed comment create, reply, resolve, or reopen failures and
post-refresh success statuses from rendering into the current document after
the user switches documents while the action is in flight.

Scope:

- Keep capturing the selected document id before each comment action.
- Ignore action failures when the selected document has changed before the
  failure returns.
- Recheck the selected document id after successful action writes and again
  after the follow-up comment-thread reload before clearing or writing success
  status.
- Add a small browser helper for current-document comment action checks.
- Add static UI regression coverage for the stale failure and post-refresh
  status guards.

Out of scope:

- Changing comment persistence, comment WebSocket payloads, permissions, review
  workflow, or notification delivery.
- Changing canonical JSON snapshots, append-only `document_events`, rollback,
  replay, schema validation, project membership, or deployment settings.
- Persisting browser comment action state across reloads.
