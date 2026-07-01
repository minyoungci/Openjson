# TASK_142_PLAN.md

## Goal

Notify active document WebSocket clients when comment threads change.

The Notes panel already uses the existing comment APIs. This task makes comment
thread creation, replies, resolve, and reopen visible to other connected users
without requiring manual refresh.

## Scope

- Broadcast `comment_threads.updated` after successful comment thread creation.
- Broadcast `comment_threads.updated` after successful comment replies.
- Broadcast `comment_threads.updated` after resolve and reopen.
- Make the static browser client reload comment threads when it receives the
  update for the currently selected document.
- Keep comment persistence in the existing `comment_threads` and append-only
  `comments` tables.

## Exclusions

- Do not add mentions, notifications, email, or per-comment subscriptions.
- Do not change comment table schemas.
- Do not create document events for comments.
- Do not implement review workflow changes, Git integration, AI features,
  branching, pull requests, or path-level permissions.

## Verification

```powershell
python -W ignore::DeprecationWarning -m unittest tests.test_realtime_collaboration tests.test_comments tests.test_static_ui
python -W ignore::DeprecationWarning -m compileall app
python -W ignore::DeprecationWarning -m unittest discover -s tests
```
