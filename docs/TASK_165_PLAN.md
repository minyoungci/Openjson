# TASK_165 Plan - Guard stale collaboration-state polling responses

Goal: prevent delayed HTTP polling fallback responses or failures from
rendering into the current collaboration panel after the user switches
documents, the current version changes, or the collaboration loop is stopped.

Scope:

- Add a browser request id for `GET /documents/{document_id}/collaboration-state`
  polling fallback requests.
- Capture selected document id and current version before sending the polling
  request.
- Apply successful polling responses only while the request id, selected
  document id, and current version still match the captured context.
- Ignore stale polling failures instead of rendering them into the active
  collaboration panel.
- Invalidate outstanding polling requests when the collaboration loop stops.
- Keep existing `collaboration_state` WebSocket payload document-id checks.
- Add static UI regression coverage for the polling guard.

Out of scope:

- Changing WebSocket payload shape.
- Changing presence rows, checkpoint generation, document events, rollback,
  replay, schema validation, or collaboration text-operation semantics.
- Persisting browser polling request state across reloads.
