# TASK_104_PLAN.md

## Objective

Move the local collaboration MVP closer to production readiness without
breaking the core versioned JSON event model.

This task adds:

- transient text-operation collaboration over WebSocket;
- commit from collaborative text session into canonical JSON document events;
- invitation email delivery through console or SMTP backends;
- refresh-token rotation for local sessions;
- OIDC SSO login/callback baseline;
- offline sync queue APIs for clients that temporarily lose network access;
- deployment readiness notes and required external inputs.

## Core Boundary

Raw collaborative text is not canonical storage.

Text-level edits may exist only as transient collaboration session state. A
collaborative text session becomes durable only when it is parsed as valid JSON
and committed through the existing document content update pipeline, creating a
normal append-only `document_events` row.

## Included

- WebSocket message types:
  - `text_session.join`
  - `text_session.op`
  - `text_session.commit`
- Simple OT transform for insert/delete text operations in one document
  session.
- Session refresh-token table and rotation APIs.
- Invitation email delivery at invitation creation time.
- SMTP env configuration with console fallback.
- OIDC login URL and callback flow for one configured provider.
- Offline sync batch API that accepts queued content saves with idempotency
  keys and reports applied/conflict/failed results per item.
- Static UI additions for invite links, collaborative text join/commit, and
  basic offline queue status.

## Explicitly Excluded

- Making raw text the source of truth.
- Persisting syntax-invalid JSON as latest snapshot.
- Multi-provider enterprise SSO admin UI.
- SCIM, SAML, domain verification, or enterprise policy administration.
- Background email retry workers.
- Full offline-first CRDT storage replication.
- Array conflict auto-resolution beyond existing safe policy.

## Deployment Inputs Needed From Owner

- Production domain and public app URL.
- SMTP provider credentials or transactional email provider.
- SSO/OIDC issuer, client id, client secret, redirect URI, and allowed domains.
- PostgreSQL and Redis deployment choice.
- TLS/reverse proxy host.
- Backup retention and restore objective.
- Production secret-management location.
