# TASK_167 Plan - Guard stale ZIP import preview/apply responses

Goal: prevent delayed ZIP import preview or apply responses from rendering into
the current project/editor after the user switches projects, selects another ZIP
file, changes the selected document, or starts a newer ZIP import action.

Scope:

- Add browser request ids for ZIP preview and ZIP apply actions.
- Track transient `zipPreviewing` and `zipApplying` states so ZIP import actions
  do not overlap with other busy editor actions.
- Capture project id and ZIP `File` object before preview and apply requests.
- For apply, also capture the preview object and selected document id before
  sending the write request.
- Apply preview and apply responses only while the request id, project id, file,
  preview object, and selected document context still match the current browser
  state.
- Ignore stale preview/apply failures instead of rendering them into the active
  ZIP import panel.
- Clear ZIP selection and invalidate outstanding ZIP import requests when
  returning to project selection, opening another project, or clearing session
  state.
- Add static UI regression coverage for the ZIP import guards.

Out of scope:

- Changing ZIP import backend APIs, schema checks, reference detection, path
  conflict rules, or transaction semantics.
- Adding stored import jobs or background workers.
- Changing canonical JSON snapshots, append-only `document_events`, rollback,
  replay, realtime collaboration, or review workflow.
