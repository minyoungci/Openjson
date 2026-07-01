# TASK_145 Plan - Human-readable collaboration actors

Goal: make collaboration monitoring and event views show signed-in user names without changing the append-only document event model.

Scope:

- Preserve `actor_id` in all audit payloads.
- Add display-name metadata to document history, event detail, version, project event feed, path history, and blame responses.
- Keep active collaboration presence focused on display name and editing state; do not expose user email there.
- Update the static editor to prefer user display names in collaboration and history panels.
- Add tests that lock the display-name contract and the presence privacy behavior.

Out of scope:

- New permission rules.
- Branching, pull requests, Git integration, or AI features.
- Rewriting historical events.
- UI redesign beyond existing collaboration/history labels.
