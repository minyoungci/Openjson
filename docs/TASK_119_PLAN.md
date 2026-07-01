# TASK_119 Plan: Project Usage Limit Guard

## Objective

Add project-level usage limits before broader public use of ZIP import,
document creation, editor saves, restore, and rollback.

The goal is not billing or paid plan enforcement. The goal is a conservative
single-instance deployment guard so one project cannot consume the SQLite disk
with active JSON snapshots.

## Scope

- Add read-only project usage API.
- Count active documents only.
- Count active latest snapshot bytes from `json_documents.current_snapshot_json`.
- Configure limits through environment variables.
- Enforce limits before document/event mutation writes.
- Include usage-limit runtime flags in `GET /version`.
- Show project usage in the static browser shell status chips.
- Add regression coverage for create, patch, rollback, and ZIP import.

## API

```text
GET /projects/{project_id}/usage
```

Response:

```json
{
  "project_id": "project_001",
  "usage": {
    "active_document_count": 2,
    "active_snapshot_bytes": 1234
  },
  "limits": {
    "enabled": true,
    "max_project_documents": 10000,
    "max_project_snapshot_bytes": 104857600
  }
}
```

## Environment

```text
OPENJSON_PROJECT_USAGE_LIMIT_ENABLED=1
OPENJSON_MAX_PROJECT_DOCUMENTS=10000
OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES=104857600
```

## Enforcement Points

- Document create
- Document patch
- Full-content editor save, including safe auto-merge
- Document restore
- Document rollback
- ZIP import preview/apply

Rejected mutations return `PROJECT_USAGE_LIMIT_EXCEEDED` before event insert,
snapshot update, version increment, or restore lifecycle update.

## Data Model

No new tables are added.

Usage is derived from existing active `json_documents` rows. The guard does not
change append-only `document_events` behavior.

## Excluded

- Billing or paid plan tiers.
- Per-user storage accounting.
- Historical event-log disk accounting.
- Background cleanup or retention jobs.
- Hard deletion or compaction.
- Cloudflare or Render account quota automation.
