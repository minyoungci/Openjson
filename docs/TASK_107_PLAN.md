# TASK_107_PLAN.md

## Objective

Make project invitation email delivery visible and operationally clear in the
user-facing UI.

The backend already supports `console`, `smtp`, and `disabled` email backends
and records each attempted delivery in `email_deliveries`. This task does not
change the project invitation token model or the JSON document event model.

## Included

- Show invitation email delivery status after creating an invite.
- Keep the generated invite token visible as a fallback join path.
- Add tests for SMTP delivery behavior without using an external SMTP service.
- Document the Render environment variables required to switch from console
  delivery to real SMTP delivery.

## Out of Scope

- Background email retry workers.
- Transactional email provider-specific APIs.
- SCIM/SAML enterprise invitation workflows.
- Changing document mutation persistence, WebSocket collaboration, review, or
  JSON event replay behavior.
