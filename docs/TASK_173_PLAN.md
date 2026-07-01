# TASK_173 Plan - Guard stale browser authentication responses

Goal: prevent delayed browser authentication responses from applying the wrong
session, clearing a newer session, or rendering stale account status after the
user starts another signup/login/logout/refresh flow, edits the auth form, or
clears session state while an auth request is in flight.

Scope:

- Add browser request ids for signup/login, logout, and refresh-token actions.
- Track transient `authenticating`, `loggingOut`, and `refreshingSession`
  state so overlapping account transitions are ignored.
- Capture auth form email/name context before calling `POST /auth/signup` or
  `POST /auth/login`.
- Apply successful signup/login responses only while the request id, captured
  form context, and pending invite token still match.
- Apply logout completion only while the request id, captured user id, and
  captured session token still match.
- Apply refresh-token rotation only while the request id and captured refresh
  token still match.
- Invalidate outstanding auth requests when the auth form changes or session
  state is cleared.
- Add static UI regression coverage for the auth request guards.

Out of scope:

- Changing backend auth APIs, session-token hashing, refresh-token rotation
  storage, invitation acceptance rules, OIDC provider behavior, permissions,
  email delivery, canonical document storage, or append-only
  `document_events` semantics.
- Changing project/document collaboration, ZIP import, document create/save,
  rollback, replay, comments, reviews, WebSocket payloads, or deployment
  settings.
- Persisting browser auth request state across reloads.
