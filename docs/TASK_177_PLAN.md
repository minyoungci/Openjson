# TASK_177 Plan - Guard stale save failure offline queue writes

Goal: prevent a delayed browser save failure from enqueueing an old document
content payload into the offline sync queue after the user switches documents,
the base version changes, or the visible editor buffer changes.

Scope:

- Keep the existing save request id and captured document/base/content guard.
- On non-API save failures, check whether the save request is still current
  before writing the captured save payload to the browser offline queue.
- Keep offline queue writes for current network failures so offline sync still
  preserves the active user's intended save.
- Add static UI regression coverage for the stale save failure guard.

Out of scope:

- Changing backend `PUT /documents/{document_id}/content` behavior.
- Changing `POST /projects/{project_id}/offline-sync`, idempotency keys,
  merge policy, permissions, canonical snapshots, append-only
  `document_events`, or stored offline sync operations.
- Persisting additional browser save request metadata across reloads.
