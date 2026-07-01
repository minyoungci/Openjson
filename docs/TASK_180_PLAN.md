# TASK_180 Plan - Guard stale clipboard copy statuses

Goal: prevent delayed browser clipboard writes from showing stale copied
statuses after the user switches projects, switches documents, edits filters,
or replaces an invitation link.

Scope:

- Add browser request id state for share-link copy actions.
- Add browser request id state for invite-link copy actions.
- Capture the project, selected document, and share URL before copying a
  share link.
- Capture the project, session user, and invite link before copying an invite
  link.
- Show copy success/fallback status only while the captured context still
  matches the current browser state.
- Invalidate invite-link copy requests when invite link fields are regenerated
  or cleared.
- Add static UI regression coverage for stale clipboard guards.

Out of scope:

- Changing share URL shape, invitation token generation, project invitation
  APIs, email delivery, permissions, canonical snapshots, or append-only
  `document_events`.
- Adding persistent clipboard history or browser permission handling.
