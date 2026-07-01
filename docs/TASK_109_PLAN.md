# TASK_109_PLAN.md

## Objective

Make invite-link onboarding complete enough for a teammate to open an official
OpenJson link, sign up or log in, and land in the invited project without
manually re-entering the token.

This task is a browser flow improvement only. It does not change invitation
token storage, project membership rules, authentication token storage, email
delivery, WebSocket collaboration, or canonical JSON document persistence.

## Included

- Preserve `?invite_token=...` as a pending invite through signup/login.
- Show invite-specific auth/project-entry status messages.
- Automatically call `POST /invitations/accept` after authentication when a
  pending invite token exists.
- Open the invited project after successful acceptance.
- Keep the token available for manual retry if acceptance fails, such as when
  the logged-in email does not match the invited email.
- Add static UI tests for the pending-invite client flow.

## Out of Scope

- Public invitation preview without authentication.
- Changing invite token hashing, expiry, or one-time acceptance policy.
- Email provider setup or retry workers.
- SSO provider configuration.
- Any change to document event replay, save, diff, rollback, or collaboration
  persistence.
