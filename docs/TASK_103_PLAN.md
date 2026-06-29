# TASK_103_PLAN.md

## Objective

Remove the practical blockers left after TASK_102 without weakening the
versioned JSON event model.

This task adds password-backed local sessions, project invitations, token-aware
WebSocket collaboration, an optional Redis realtime backplane, and conservative
safe auto-merge for stale raw JSON editor saves.

## Included

- Password-backed local signup and login APIs.
- Bearer session tokens that can authenticate existing HTTP APIs.
- Logout and current-user read APIs.
- Project invitation create/list/accept APIs.
- WebSocket authentication by session/API bearer token query parameter.
- Optional Redis realtime backplane through `OPENJSON_REDIS_URL`.
- Safe path-level auto-merge for stale full-content saves when:
  - client/server changed paths do not overlap;
  - no changed path touches an array;
  - resulting JSON still passes canonical and schema validation.
- Static UI controls for login/signup, invite creation/acceptance, and
  auto-merge opt-in.

## Explicitly Excluded

- Enterprise SSO.
- Email delivery for invitations.
- Offline sync.
- Git integration, branching, pull requests, or AI features.
- Full CRDT/OT raw-text co-editing. Raw text can still be temporarily invalid
  in the browser only; persisted state remains valid JSON Patch events.

## Design Rules

- Session and invitation tokens are stored only as hashes.
- Passwords are stored as PBKDF2-SHA256 hashes with per-password salts.
- Accepted auto-merge saves still create exactly one append-only
  `document_events` row.
- Auto-merge failure creates no document event and changes no snapshot.
- Arrays are intentionally excluded from auto-merge because index-based array
  patches are unsafe under concurrent edits.
