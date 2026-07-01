# TASK_108_PLAN.md

## Objective

Make project invitations shareable through a full app URL even when production
SMTP credentials are not configured yet.

This task improves the user-facing invite handoff only. It does not change the
project invitation token model, authentication model, document event model,
WebSocket collaboration behavior, or email delivery backend.

## Included

- Show a full `/app?invite_token=...` invite URL after creating a project
  invitation.
- Add a copy control for the generated invite URL.
- Keep the raw invite token visible as a fallback.
- Keep existing `?invite_token=...` URL parsing so invited users can sign up or
  log in and then join the project from the project entry screen.
- Add static UI tests for the invite URL elements and client code.

## Out of Scope

- SMTP provider configuration.
- Email retry workers.
- Public self-serve project discovery.
- Changing invitation token hashing or storage.
- Changing canonical JSON document mutation persistence.
