# TASK_146 Plan - Human-readable comment authors

Goal: make the Notes panel readable for real team use by showing user display
names for comment thread creators, resolvers, and comment authors.

Scope:

- Preserve `created_by`, `resolved_by`, and `author_id` identifiers for audit
  compatibility.
- Add display-name metadata to comment thread and comment read payloads.
- Update the static editor Notes panel to prefer display names with identifier
  fallbacks.
- Add regression tests for service payloads and static UI strings.

Out of scope:

- Editing or deleting comments.
- Changing append-only comment storage.
- New permission rules.
- Email exposure in comment payloads.
