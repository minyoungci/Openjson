# TASK_032 Plan - Project Export Event-Chain Integrity

## Goal

Harden the read-only project export archive so its `integrity` section reports
both:

- replay consistency
- event-chain metadata integrity

TASK_019 added the export archive with replay-only integrity. TASK_032 aligns
that archive with the later replay/event-chain diagnostic surface so an export
can show when the latest snapshot is reconstructable but event metadata is not
trustworthy.

## Non-Goals

- No Git integration, file checkout, ZIP generation, object storage, or
  background export job.
- No persisted export table, cache, or integrity result table.
- No mutation, repair, event rewrite, or snapshot rewrite.
- No schema change.
- No UI work.
- No branch, pull request, realtime collaboration, WebSocket, offline sync,
  merge automation, or AI features.
- No complex path-level permission model.

## API

No endpoint change.

`GET /projects/{project_id}/export`

The endpoint remains read-only and permission-gated by `export:read`.

## Response Policy

Keep existing export fields for compatibility:

- `integrity.replay_consistent`
- `integrity.document_count`
- `integrity.document_event_count`
- `integrity.documents`

Add event-chain-aware fields:

```json
{
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

The top-level integrity `status` is `ok` only when replay and event-chain
checks are both `ok`.

The export API should still return the archive payload even when integrity is
`failed`; the failure is diagnostic, not a write gate.
TASK_039 later extends this behavior so malformed persisted snapshot or event
JSON is returned as structured export diagnostics instead of a server error.

## Data Model

No schema change.

The export reads existing `json_documents` and `document_events` rows only.

## Tests

- Export integrity reports both replay and event-chain checks for healthy
  documents.
- Export read remains non-mutating.
- Export integrity reports failed event-chain metadata even when replay remains
  ok.
- HTTP export includes the same event-chain-aware integrity fields.
