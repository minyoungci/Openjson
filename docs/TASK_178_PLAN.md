# TASK_178 Plan - Refresh expired sessions for binary upload requests

Goal: keep ZIP preview/apply uploads working when the browser access token has
expired but the refresh token is still valid.

Scope:

- Align `apiFetchBinary()` with the existing JSON `apiFetch()` authentication
  retry policy.
- Send bearer authentication only when auth is enabled for the binary request.
- On HTTP 401, call `refreshAccessToken()` once when a refresh token is
  available and the request is not already retrying.
- Retry the original binary request after a successful refresh.
- Add static UI regression coverage for the binary API refresh behavior.

Out of scope:

- Changing refresh-token rotation storage or backend auth endpoints.
- Changing ZIP import preview/apply endpoints, import transactions, usage
  limits, permissions, canonical snapshots, or append-only `document_events`.
- Adding resumable uploads or chunked upload state.
