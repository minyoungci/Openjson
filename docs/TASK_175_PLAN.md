# TASK_175 Plan - Guard stale browser offline sync responses

Goal: prevent delayed browser offline-sync responses from clearing the wrong
queued saves, showing stale sync status, or reloading the wrong document after
the user switches projects, switches documents, clears session state, or starts
a newer offline-sync flush.

Scope:

- Add browser request id state for offline-sync flushes.
- Track transient `syncingOffline` state so overlapping offline-sync flushes
  are ignored.
- Capture session user id, project id, selected document id, and the queued
  offline items before calling `POST /projects/{project_id}/offline-sync`.
- Submit the captured queue snapshot instead of the mutable live queue array.
- Apply successful sync responses only while the request id, session user id,
  project id, selected document id, and queued item ids still match.
- Preserve any queued item that was added after the in-flight sync started.
- Invalidate outstanding offline-sync requests on project/session/document
  changes and editor reloads.
- Add static UI regression coverage for the offline-sync request guard.

Out of scope:

- Changing backend offline-sync APIs, idempotency keys, conflict policy,
  permissions, canonical document storage, append-only `document_events`, or
  WebSocket collaboration behavior.
- Changing ZIP import, document create/save, rollback, replay, comments,
  reviews, authentication, invitation, or deployment settings.
- Persisting browser offline-sync request state across reloads.
