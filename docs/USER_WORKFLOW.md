# OpenJson User Workflow

## Entry Flow

OpenJson now uses a user-facing entry flow:

1. Sign up or log in with name, email, and password.
2. Create a workspace/project or open an existing project.
3. Upload or create JSON documents inside that selected project.

The app still keeps `actor_id`, `project_id`, and session tokens internally, but
normal users no longer need to paste those values into the top bar.

Project owners/admins can invite teammates by email from the Team panel. If the
deployment is configured with SMTP, OpenJson sends the invitation email
immediately. The generated invite link and raw invite token remain visible as
fallback join paths, so a teammate can open the official app URL, sign up or log
in with the invited email address, and join the project.

## How Saving Works

The editor does not persist raw text directly as the source of truth.

When a user presses Save, commits live text, or autosave runs:

1. The browser sends the current JSON text and the document `base_version`.
2. The server parses the text as JSON.
3. The server compares the old snapshot and new snapshot to derive JSON patch
   operations.
4. The server validates the candidate JSON snapshot.
5. If validation passes and the base version is current, the server stores a new
   append-only `document_events` row.
6. The latest document snapshot and version are updated after the event is
   accepted.

If JSON is invalid, schema validation fails, or the base version is stale, the
save is rejected and no durable event is created.

## How Realtime Updates Work

Realtime collaboration is based on accepted checkpoints.

- Presence shows which users are active in the document.
- New saved versions appear as checkpoints in the Collaboration panel.
- If another user saves while your editor is clean, the app can load the newer
  checkpoint.
- If another user saves while you have unsaved local edits, the app warns you to
  reload or resolve the conflict before saving.
- Live Text is transient while typing. It becomes durable only when committed as
  valid JSON through the same event pipeline.

## How Notes and Memos Work

Notes are stored as comment threads and comments, not inside the JSON snapshot.

- A thread can be attached to a document, JSON path, or change context.
- Adding, resolving, or reopening a note changes comment data only.
- JSON document versions change only when an accepted document mutation creates
  a new document event.
