# TASK_001.md — Build the Versioned JSON Document Foundation

## Objective

Implement the foundational backend for versioned JSON document storage.

The goal is to support JSON document creation, retrieval, patch-based update, event logging, version tracking, and rollback.

Do not implement realtime collaboration, comments, review workflow, or complex permissions in this task.

---

## Required Reading

Before coding, read:

- AGENTS.md
- docs/TECH_SPEC.md

---

## Scope

Implement the following:

1. Basic project/document data model
2. JSON document creation
3. JSON document retrieval
4. JSON document patch update
5. Document version increment
6. Append-only document event log
7. Inverse patch generation
8. Version conflict detection
9. Document history API
10. Rollback API
11. Event replay consistency test

---

## Required Entities

Implement at minimum:

### JsonDocument

Fields:

- id
- project_id
- full_path
- current_version
- current_snapshot_json
- created_by
- created_at
- updated_at
- deleted_at

### DocumentEvent

Fields:

- id
- document_id
- actor_id
- base_version
- result_version
- patch
- inverse_patch
- changed_paths
- before_values
- after_values
- summary
- reason
- created_at

---

## Required APIs

### Create Document

POST /projects/:project_id/documents

Request:

{
  "full_path": "config/model.json",
  "content": {
    "model": "baseline",
    "learning_rate": 0.001
  }
}

Behavior:

- Validate that content is valid JSON.
- Create JsonDocument with current_version = 1.
- Create initial DocumentEvent.
- Return document metadata and current snapshot.

---

### Get Document

GET /documents/:document_id

Response:

{
  "id": "doc_001",
  "project_id": "project_001",
  "full_path": "config/model.json",
  "current_version": 1,
  "content": {
    "model": "baseline",
    "learning_rate": 0.001
  }
}

---

### Patch Document

PATCH /documents/:document_id

Request:

{
  "base_version": 1,
  "patch": [
    {
      "op": "replace",
      "path": "/learning_rate",
      "value": 0.0005
    }
  ],
  "reason": "Update default learning rate"
}

Behavior:

- Check base_version against current_version.
- If mismatched, return VERSION_CONFLICT.
- Apply patch.
- Generate inverse patch.
- Store DocumentEvent.
- Update current_snapshot_json.
- Increment current_version.
- Return updated document metadata.

---

### Get History

GET /documents/:document_id/history

Response should include ordered DocumentEvent records.

---

### Rollback

POST /documents/:document_id/rollback

Request:

{
  "target_version": 1,
  "reason": "Rollback to stable config"
}

Behavior:

- Reconstruct target version.
- Create a new rollback event.
- Do not delete previous events.
- Update current snapshot to target version content.
- Increment version.

---

## Error Requirements

Implement at minimum:

- DOCUMENT_NOT_FOUND
- INVALID_JSON_SYNTAX
- VERSION_CONFLICT
- PATCH_APPLY_FAILED
- INTERNAL_ERROR

---

## Tests Required

Add tests for:

1. Create valid JSON document
2. Reject invalid JSON document
3. Patch document successfully
4. Reject patch with wrong base_version
5. Store DocumentEvent after patch
6. Generate inverse patch
7. Rollback creates a new event
8. Rollback does not delete previous events
9. Replay all events reconstructs latest snapshot

---

## Definition of Done

This task is complete only when:

- All required APIs work.
- All required tests pass.
- Event replay reconstructs latest snapshot exactly.
- Rollback is implemented as a new event, not history deletion.
- No realtime collaboration code is added.
- No review workflow code is added.
- No unrelated UI work is added.

At the end, report:

- implemented files
- database schema
- API endpoints
- test results
- limitations
- recommended next task
