# TASK_140_PLAN.md

## Goal

Reset stale live-text sessions when the canonical document version changes
outside the active in-memory text session.

The transient text session is anchored to the document version used when the
session was created. If another save path advances `json_documents.current_version`,
the existing text session must not keep serving old raw text or keep committing
with a stale `base_version`.

## Scope

- Detect `document.current_version != text_session.document_version` during
  `text_session.join`.
- Replace the in-memory text session with the latest editor-state
  `content_text` from the canonical document.
- Include reset metadata in `text_session.state` so clients can preserve dirty
  local buffers and re-diff against the latest canonical text.
- Return `VERSION_CONFLICT` when a client sends a text operation whose
  `base_text_revision` is ahead of the reset session revision.
- Keep raw live-text state transient; durable JSON still changes only through
  accepted content saves that create append-only `document_events`.

## Exclusions

- Do not persist text-session operations.
- Do not add a CRDT or multi-operation transform protocol.
- Do not change SQLite schemas or durable document event schemas.
- Do not implement automatic merge of uncommitted text-session edits after an
  external document save.

## Verification

```powershell
python -W ignore::DeprecationWarning -m unittest tests.test_realtime_collaboration tests.test_task104_collaboration_auth_sync tests.test_static_ui
python -W ignore::DeprecationWarning -m compileall app
python -W ignore::DeprecationWarning -m unittest discover -s tests
```
