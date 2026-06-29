# AGENTS.md — Collaborative JSON DB Workspace

You are working on a web service for collaborative management of JSON-based structured databases.

The product is not a simple JSON editor. It is a JSON-native collaborative data workspace where teams can edit, validate, comment, review, track, diff, and roll back JSON documents.

Before writing code, read:

- docs/TECH_SPEC.md
- docs/API_SPEC.md if available
- docs/DATA_MODEL.md if available
- current TASK_XXX.md file

If any of these files are missing, create a minimal version only when required for the current task.

---

## 1. Core Product Principle

The core unit of the system is not a whole JSON file.

The core unit is a validated, auditable, JSON path-level change event.

Every important implementation decision must preserve the following principle:

> Latest JSON snapshot is for fast access.  
> Append-only event log is for trust, audit, diff, blame, and rollback.

Do not build the system as a simple file overwrite service.

---

## 2. Source of Truth

The system should use a hybrid source-of-truth model:

1. Latest JSON snapshot
   - Used for fast document loading and current state display.

2. Append-only document event log
   - Used for history, audit, rollback, blame, diff, and reconstruction.

The latest snapshot and event log must never silently diverge.

A critical invariant:

> Replaying document events from the initial state must reconstruct the latest snapshot exactly.

Any implementation that violates this invariant is wrong.

---

## 3. Technical Priorities

Implement in this order:

1. Project and document structure
2. JSON document CRUD
3. JSON syntax validation
4. Versioned event log
5. Patch apply and inverse patch generation
6. History and diff
7. Rollback
8. JSON Schema validation
9. Path-level comments
10. Permission model
11. Realtime collaboration
12. Review workflow

Do not start with realtime collaboration.

Realtime collaboration is important, but it should be added only after the document event model, versioning, validation, and rollback are reliable.

---

## 4. MVP Scope

The first MVP should support:

- Workspace
- Project
- Folder-like document path
- JSON document create/read/update/delete
- Current JSON snapshot
- Version number
- JSON patch-like update request
- Append-only document event log
- Before/after value tracking
- JSON syntax validation
- Basic history API
- Basic diff API
- Basic rollback API

Do not implement these in the first MVP unless explicitly requested:

- Full GitHub-like pull request workflow
- Branching
- Real-time text collaboration
- Offline-first sync
- Complex path-level permissions
- Enterprise SSO
- AI assistant features
- Git import/export
- Billing
- Large binary file support

---

## 5. Hard Rules

Do not overwrite JSON documents without recording an event.

Do not allow mutation without actor information.

Do not allow mutation without base version information.

Do not allow invalid JSON to become the latest canonical snapshot.

Do not physically delete document history by default.

Do not implement rollback by deleting previous events.

Rollback must be recorded as a new event.

Do not treat Git as the primary backend storage.

Git import/export may be added later, but the internal source of truth should be the database event log and snapshot model.

Do not assume array operations are safe.

Array index-based patches can be dangerous during concurrent edits. Prefer identity-based object maps for records when possible.

---

## 6. Data Model Requirements

The implementation must support at least these core entities:

- User
- Workspace
- Project
- JsonDocument
- DocumentEvent
- Schema
- CommentThread
- Comment
- Permission

For the first MVP, implement at minimum:

- User
- Workspace
- Project
- JsonDocument
- DocumentEvent

JsonDocument must include:

- id
- project_id
- full_path
- current_version
- current_snapshot_json
- created_by
- created_at
- updated_at
- deleted_at nullable

DocumentEvent must include:

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
- reason nullable
- created_at

---

## 7. Patch and Versioning Rules

All document updates must include:

- document_id
- actor_id
- base_version
- patch
- optional reason

The server must:

1. Load the current document.
2. Check that base_version equals current_version.
3. Apply the patch.
4. Validate resulting JSON syntax and structure.
5. Generate inverse patch.
6. Store DocumentEvent.
7. Update JsonDocument current snapshot and version.
8. Return new version and validation result.

If base_version does not match current_version, return VERSION_CONFLICT.

Do not silently merge conflicting updates in the MVP.

---

## 8. Validation Rules

Validation levels:

1. JSON syntax validation
2. JSON Schema validation
3. Custom project validation
4. Review gate validation

MVP only requires JSON syntax validation.

However, design the validation interface so that JSON Schema validation can be added later without rewriting the document update pipeline.

Validation result format should include:

- valid
- errors
- warnings
- path
- message
- severity
- validation_level

---

## 9. API Design Rules

Prefer explicit and boring APIs.

Do not over-engineer GraphQL unless requested.

Initial REST API should include:

- POST /workspaces
- GET /workspaces
- POST /workspaces/:workspace_id/projects
- GET /projects/:project_id
- POST /projects/:project_id/documents
- GET /documents/:document_id
- PATCH /documents/:document_id
- DELETE /documents/:document_id
- GET /documents/:document_id/history
- GET /documents/:document_id/diff
- POST /documents/:document_id/rollback

All mutation APIs must enforce permission checks, even if the initial permission implementation is simple.

---

## 10. Error Handling

Use consistent error response format.

Required error codes:

- AUTH_REQUIRED
- PERMISSION_DENIED
- WORKSPACE_NOT_FOUND
- PROJECT_NOT_FOUND
- DOCUMENT_NOT_FOUND
- INVALID_JSON_SYNTAX
- VERSION_CONFLICT
- PATCH_APPLY_FAILED
- SCHEMA_VALIDATION_FAILED
- REVIEW_REQUIRED
- INTERNAL_ERROR

Example:

{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "Document version conflict. Please reload the latest version.",
    "details": {
      "client_base_version": 12,
      "server_current_version": 14
    }
  }
}

---

## 11. Testing Requirements

Every implementation must include tests for:

- JSON document creation
- JSON syntax validation
- patch application
- inverse patch generation
- event log creation
- version increment
- version conflict
- rollback
- event replay reconstruction
- document soft delete

The most important test:

> Replay all events and verify that the reconstructed document equals the latest snapshot.

Do not consider the versioning system complete until this test passes.

---

## 12. Development Behavior

Work incrementally.

Before implementing a large feature, write a short implementation plan.

For each task, report:

- files changed
- data model changes
- API changes
- tests added
- known limitations
- next recommended task

Do not implement unrelated features.

Do not silently change the product direction.

Do not add dependencies unless they clearly reduce complexity.

Prefer simple, inspectable code over clever abstractions.

---

## 13. First Implementation Target

The first goal is not to build the full collaborative product.

The first goal is to prove that the system can safely store and update JSON documents with versioned, auditable, replayable events.

Build the foundation first.

Realtime collaboration, comments, review, and schema validation should be added only after this foundation is stable.
