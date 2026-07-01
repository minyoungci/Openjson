# TASK_134_PLAN.md

## Goal

Keep browser live-text shadow state aligned with the server session after
accepted operations.

The server may transform a submitted text operation when another user's
operation was accepted first. If the browser ignores its own accepted operation
payload and keeps only optimistic local shadow text, the browser can drift from
the server text session and later generate incorrect diffs.

## Scope

- Include authoritative current `content_text` in `text_session.op.accepted`.
- Preserve idempotent replay behavior from TASK_132.
- Make the browser use `content_text` to realign `liveTextShadow`.
- Keep the user's editor buffer intact for local self-acknowledgements, so
  keystrokes typed while waiting for an acknowledgement are re-diffed after the
  acknowledgement.
- Keep remote accepted operations reflected into the visible editor buffer.

## Exclusions

- Do not persist transient text-session state.
- Do not change `document_events`, latest snapshots, rollback, or replay.
- Do not implement a full CRDT or OT client library.
- Do not change the content save or autosave API contracts.

## Verification

```powershell
python -m unittest tests.test_realtime_collaboration tests.test_static_ui
python -m unittest tests.test_task104_collaboration_auth_sync
python -m unittest discover -s tests
```
