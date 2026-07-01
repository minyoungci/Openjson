# TASK_147 Plan - Editor cursor path presence

Goal: make realtime monitoring more useful by showing where each active user is
currently working in the JSON document.

Scope:

- Reuse existing transient `editor_presence.cursor_path`.
- Derive a conservative JSON Pointer from the raw editor cursor position in the
  browser.
- Send `cursor_path` through both WebSocket presence and HTTP polling fallback.
- Show the cursor path in the active-users collaboration panel.
- Add focused regression coverage for HTTP presence and static UI contracts.

Out of scope:

- Persisting cursor history.
- Path-level permissions.
- Validating that the cursor path exists in the latest canonical snapshot.
- Replacing the existing raw textarea editor with a structured tree editor.
