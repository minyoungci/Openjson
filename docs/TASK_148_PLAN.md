# TASK_148 Plan - Explicit browser presence leave

Goal: keep realtime monitoring accurate when a user switches documents or
leaves the editor.

Scope:

- Track the document id that currently owns the browser presence heartbeat.
- Send `DELETE /documents/{document_id}/presence` for that active document when
  the collaboration loop stops.
- Keep the existing `beforeunload` leave path.
- Preserve timeout-based cleanup for abrupt disconnects.
- Add static UI regression coverage for the active presence document contract.

Out of scope:

- Persisting presence history.
- Changing `editor_presence` schema.
- Server-side forced leave broadcasts.
- Multi-document simultaneous editing from one browser tab.
