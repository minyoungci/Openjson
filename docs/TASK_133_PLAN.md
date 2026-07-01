# TASK_133_PLAN.md

## Goal

Harden browser live-text editing so consecutive local keystrokes respect server
acknowledgement order.

The WebSocket server uses `base_text_revision` to transform text operations.
If the browser sends multiple local operations before the first accepted
operation is acknowledged, later operations can carry a stale base revision
while their indexes were computed against optimistic local text. That can shift
the operation to the wrong character position.

## Scope

- Track one pending live-text operation in the static browser UI.
- Do not send another `text_session.op` while the previous local operation is
  waiting for `text_session.op.accepted`.
- After the accepted acknowledgement arrives, compare the editor buffer with
  the acknowledged shadow text and send the remaining diff.
- Do not commit a live-text session while a local text operation is still
  syncing.
- Keep the server protocol and canonical document-event persistence unchanged.

## Exclusions

- Do not implement a full CRDT client.
- Do not persist transient text operations.
- Do not change `document_events` or latest snapshot semantics.
- Do not change autosave/content-save APIs.

## Verification

```powershell
python -m unittest tests.test_static_ui
python -m unittest tests.test_realtime_collaboration
python -m unittest discover -s tests
```
