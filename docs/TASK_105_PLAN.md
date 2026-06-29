# TASK_105_PLAN.md

## Objective

Prepare the current OpenJson MVP for the easiest managed Render deployment.

This task does not change the document event model, JSON mutation pipeline,
collaboration behavior, review flow, schema validation behavior, or UI product
features.

## Deployment Shape

- Render Blueprint deployment from GitHub.
- One Docker web service.
- One attached persistent disk mounted at `/data`.
- SQLite database stored at `/data/openjson.sqlite3`.
- Single service instance.
- Public URL: `https://openjson.thelumen.work`.

## Included

- `render.yaml` for Render Blueprint setup.
- Docker start command compatible with Render's `PORT` environment variable.
- Git ignore rules for local databases, caches, generated output, and secrets.
- Render deployment usage document.

## Explicitly Excluded

- PostgreSQL migration.
- Multi-instance realtime scaling.
- Managed Redis/Key Value provisioning.
- SMTP provider setup.
- OIDC provider setup.
- SAML/SCIM.
- Billing, metering, or enterprise administration.

## Important Limitation

The current application storage layer is SQLite. A Render persistent disk is
acceptable for an initial single-instance deployment, but real production
multi-user scaling should move the canonical database to PostgreSQL before
running multiple app instances or depending on higher availability.
