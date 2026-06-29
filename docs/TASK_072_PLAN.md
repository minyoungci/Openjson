# TASK_072_PLAN.md

## Objective

Harden schema `file_pattern` matching so automatic schema binding and
schema-match preview behave the same on every supported local platform.

## Problem

Python `fnmatch.fnmatch()` applies OS-dependent case normalization. On Windows,
`CONFIG/MODEL.JSON` can match `config/*.json`, even though document paths in
this service are stored as canonical POSIX-style `full_path` strings.

That makes schema binding dependent on the host OS instead of the stored
document path contract.

## Policy

- Continue accepting relative POSIX-style schema glob patterns from TASK_071.
- Match `schemas.file_pattern` against `json_documents.full_path` exactly.
- Use case-sensitive matching for both:
  - document create automatic schema binding
  - `GET /projects/{project_id}/schema-matches`
- Keep the current simple `fnmatch` glob semantics, including the existing
  `config/*.json` nested path behavior.
- Do not add schema priority rules, schema update/deactivate APIs, UI work,
  realtime collaboration, Git integration, branching, pull requests, or AI
  features.

## Implementation

- Replace `fnmatch.fnmatch(...)` with `fnmatch.fnmatchcase(...)` in schema
  binding and schema-match preview.
- Add service and HTTP tests proving `config/*.json` matches
  `config/model.json` but not `CONFIG/model.json`.

## Verification

- Related schema tests must pass.
- Full test suite must pass.
- No forbidden feature scope may be introduced.
