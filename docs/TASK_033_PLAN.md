# TASK_033 Plan - Validation Report Integrity Context

## Goal

Harden the read-only project validation report so schema validation output is
shown together with event-log integrity context.

The existing validation report answers whether latest snapshots pass their
bound schemas. TASK_033 adds a separate `integrity` section so callers can tell
whether those latest snapshots are backed by trustworthy replay and event-chain
metadata.

## Non-Goals

- No custom validation engine.
- No schema update/deactivate endpoint.
- No document mutation, auto-fix, event write, audit write, repair, or snapshot
  rewrite.
- No persisted validation or integrity result table.
- No UI work.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No complex path-level permission model.

## API

No endpoint change.

`GET /projects/{project_id}/validation-report`

The endpoint remains read-only and permission-gated by `document:validate`.

## Response Policy

Keep the existing top-level validation `status` semantics:

- `valid`: no schema-invalid documents among checked documents
- `invalid`: at least one schema-invalid document among checked documents

Add an independent `integrity` envelope:

```json
{
  "status": "valid",
  "integrity": {
    "status": "failed",
    "replay_consistent": true,
    "event_chain_consistent": false,
    "checks": {
      "replay": {
        "status": "ok"
      },
      "event_chain": {
        "status": "failed"
      }
    }
  }
}
```

`integrity.status` is `ok` only when replay and event-chain checks both pass.

`only_invalid=true` still filters the returned `documents` list by schema
validity only. The top-level `integrity` envelope still covers all checked
documents so event metadata failures are not hidden by the validation filter.

## Data Model

No schema change.

The endpoint reads existing `json_documents`, bound `schemas`, and
`document_events` rows only.

## Tests

- Healthy validation report includes replay and event-chain integrity context.
- Validation report read remains non-mutating.
- Event-chain metadata failure is reported even when schema validation is
  otherwise valid.
- `only_invalid=true` does not hide top-level integrity failures.
- HTTP validation report includes the same integrity envelope.
