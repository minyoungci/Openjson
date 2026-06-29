from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import DEFAULT_DB_PATH, connect, init_db, utc_now


DEV_USER_ID = "user_dev"
DEV_EDITOR_ID = "user_dev_editor"
DEV_REVIEWER_ID = "user_dev_reviewer"
DEV_VIEWER_ID = "user_dev_viewer"
DEV_WORKSPACE_ID = "workspace_dev"
DEV_PROJECT_ID = "project_dev"
DEV_PROJECT_MEMBER_ID = "pm_project_dev_user_dev"
DEV_EDITOR_MEMBER_ID = "pm_project_dev_user_dev_editor"
DEV_REVIEWER_MEMBER_ID = "pm_project_dev_user_dev_reviewer"
DEV_VIEWER_MEMBER_ID = "pm_project_dev_user_dev_viewer"


def seed(db_path: str) -> dict[str, str]:
    init_db(db_path)
    now = utc_now()
    with connect(db_path) as conn:
        for user_id, email, display_name in (
            (DEV_USER_ID, "dev@example.com", "Dev User"),
            (DEV_EDITOR_ID, "dev-editor@example.com", "Dev Editor"),
            (DEV_REVIEWER_ID, "dev-reviewer@example.com", "Dev Reviewer"),
            (DEV_VIEWER_ID, "dev-viewer@example.com", "Dev Viewer"),
        ):
            conn.execute(
                """
                INSERT INTO users (id, email, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    email = excluded.email,
                    display_name = excluded.display_name,
                    updated_at = excluded.updated_at
                """,
                (user_id, email, display_name, now, now),
            )
        conn.execute(
            """
            INSERT INTO workspaces (id, name, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                owner_id = excluded.owner_id,
                updated_at = excluded.updated_at
            """,
            (DEV_WORKSPACE_ID, "Dev Workspace", DEV_USER_ID, now, now),
        )
        conn.execute(
            """
            INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                workspace_id = excluded.workspace_id,
                name = excluded.name,
                description = excluded.description,
                updated_at = excluded.updated_at
            """,
            (DEV_PROJECT_ID, DEV_WORKSPACE_ID, "Dev Project", "Seeded TASK_001 project", now, now),
        )
        for member_id, user_id, role in (
            (DEV_PROJECT_MEMBER_ID, DEV_USER_ID, "owner"),
            (DEV_EDITOR_MEMBER_ID, DEV_EDITOR_ID, "editor"),
            (DEV_REVIEWER_MEMBER_ID, DEV_REVIEWER_ID, "reviewer"),
            (DEV_VIEWER_MEMBER_ID, DEV_VIEWER_ID, "viewer"),
        ):
            conn.execute(
                """
                INSERT INTO project_members (id, project_id, user_id, role, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, user_id) DO UPDATE SET
                    role = excluded.role
                """,
                (member_id, DEV_PROJECT_ID, user_id, role, now),
            )
    return {
        "db_path": db_path,
        "actor_id": DEV_USER_ID,
        "editor_actor_id": DEV_EDITOR_ID,
        "reviewer_actor_id": DEV_REVIEWER_ID,
        "viewer_actor_id": DEV_VIEWER_ID,
        "workspace_id": DEV_WORKSPACE_ID,
        "project_id": DEV_PROJECT_ID,
        "project_role": "owner",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed local dev data for TASK_001 document API testing.")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("OPENJSON_DB_PATH", DEFAULT_DB_PATH),
        help="SQLite DB path. Defaults to OPENJSON_DB_PATH or ./openjson.sqlite3.",
    )
    args = parser.parse_args()
    print(json.dumps(seed(args.db_path), indent=2))


if __name__ == "__main__":
    main()
