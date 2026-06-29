# TASK_046 Plan - Review Change JSON Diagnostics

## Goal

Make persisted review proposal JSON fields diagnosable and safe.

`review_request_changes` stores proposed JSON Patch data before review apply.
Normal creation writes canonical JSON, but a local database can still be
corrupted manually. Review reads should expose the immutable proposal metadata
with diagnostics, while review apply must not partially mutate documents if a
stored proposal JSON field is malformed.

## Non-Goals

- No review workflow expansion.
- No review close endpoint.
- No branch, pull request, Git integration, realtime collaboration, WebSocket,
  offline sync, merge automation, or AI features.
- No UI work.
- No complex path-level permission model.
- No DB schema change.
- No repair or rewrite of immutable review proposal rows.

## Covered Surfaces

- `GET /projects/{project_id}/review-requests`
- `GET /review-requests/{review_request_id}`
- review decision responses that include the review payload
- `POST /review-requests/{review_request_id}/apply`
- `GET /projects/{project_id}/export`

## Behavior

For review read/export responses:

- review request metadata remains readable
- malformed `patch` or `changed_paths` is returned as `null`
- the affected change includes `json_errors`

For review apply:

- malformed stored proposal JSON stops apply before document mutation
- error code is `INTERNAL_ERROR`
- `details.diagnostic_code` is `REVIEW_CHANGE_JSON_DECODE_FAILED`
- details include review id, change id, document id, field, and JSON decoder
  details
- no document event, snapshot update, or review status change is committed

## Data Model

No schema change.

`review_request_changes` remains immutable. This task only changes how
malformed persisted JSON is reported.

## Tests

- Review get/list returns malformed change fields as `null` with `json_errors`.
- Project export returns malformed review changes with `json_errors`.
- Review apply rejects malformed stored patch JSON without partial document or
  review status mutation.
