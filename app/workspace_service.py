from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from app.audit_service import record_audit_event
from app.database import connect, utc_now
from app.errors import AppError, ErrorCode
from app.permissions import ProjectPermission, require_actor, require_project_permission


PROJECT_ROLES = {"owner", "admin", "editor", "reviewer", "viewer"}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _ensure_text(value: str | None, field: str) -> str:
    if value is None or not value.strip():
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"{field} is required.",
            {"field": field},
        )
    return value.strip()


def _ensure_email(value: str | None) -> str:
    email = _ensure_text(value, "email").lower()
    if "@" not in email:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "email must be a valid address-like value.",
            {"field": "email"},
        )
    return email


def _workspace_row(conn: sqlite3.Connection, workspace_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.WORKSPACE_NOT_FOUND,
            "Workspace not found.",
            {"workspace_id": workspace_id},
        )
    return row


def _project_row(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.PROJECT_NOT_FOUND,
            "Project not found.",
            {"project_id": project_id},
        )
    return row


def _ensure_role(role: str | None) -> str:
    normalized = _ensure_text(role, "role")
    if normalized not in PROJECT_ROLES:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Project role is not supported.",
            {"role": normalized, "supported_roles": sorted(PROJECT_ROLES)},
        )
    return normalized


def _user_row(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.USER_NOT_FOUND,
            "User not found.",
            {"user_id": user_id},
        )
    return row


def _project_member_row(conn: sqlite3.Connection, project_id: str, user_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT project_members.*,
               users.email AS email,
               users.display_name AS display_name
        FROM project_members
        JOIN users ON users.id = project_members.user_id
        WHERE project_members.project_id = ? AND project_members.user_id = ?
        """,
        (project_id, user_id),
    ).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.PROJECT_MEMBER_NOT_FOUND,
            "Project member not found.",
            {"project_id": project_id, "user_id": user_id},
        )
    return row


def _owner_count(conn: sqlite3.Connection, project_id: str) -> int:
    return conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM project_members
        WHERE project_id = ? AND role = 'owner'
        """,
        (project_id,),
    ).fetchone()["count"]


def _project_workspace_id(conn: sqlite3.Connection, project_id: str) -> str | None:
    row = conn.execute("SELECT workspace_id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return None
    return row["workspace_id"]


def _record_project_member_audit_failure(
    db_path: str,
    *,
    action: str,
    project_id: str,
    actor_id: str | None,
    user_id: str,
    role: str | None = None,
    error: AppError,
) -> None:
    details: dict[str, Any] = {
        "project_id": project_id,
        "target_user_id": user_id,
        "error_details": error.details,
    }
    if role is not None:
        details["role"] = role
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        record_audit_event(
            conn,
            actor_id=actor_id,
            workspace_id=_project_workspace_id(conn, project_id),
            project_id=project_id,
            action=action,
            target_type="project_member",
            target_id=user_id,
            outcome="failure",
            error_code=error.code,
            details=details,
        )


def _ensure_not_last_owner_change(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    current_role: str,
    next_role: str | None,
) -> None:
    if current_role != "owner":
        return
    if next_role == "owner":
        return
    if _owner_count(conn, project_id) <= 1:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Project must retain at least one owner.",
            {"project_id": project_id},
        )


def _require_workspace_access(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    actor_id: str | None,
) -> sqlite3.Row:
    require_actor(conn, actor_id)
    row = _workspace_row(conn, workspace_id)
    if row["owner_id"] == actor_id:
        return row
    membership = conn.execute(
        """
        SELECT project_members.id
        FROM projects
        JOIN project_members ON project_members.project_id = projects.id
        WHERE projects.workspace_id = ? AND project_members.user_id = ?
        LIMIT 1
        """,
        (workspace_id, actor_id),
    ).fetchone()
    if membership is None:
        raise AppError(
            ErrorCode.PERMISSION_DENIED,
            "Actor is not allowed to access this workspace.",
            {"actor_id": actor_id, "workspace_id": workspace_id},
        )
    return row


def _row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_workspace(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "owner_id": row["owner_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_project(row: sqlite3.Row, role: str | None = None) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if role is not None:
        payload["role"] = role
    return payload


def _row_to_project_member(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "user_id": row["user_id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


def create_user(
    db_path: str,
    *,
    email: str,
    display_name: str,
) -> dict[str, Any]:
    email = _ensure_email(email)
    display_name = _ensure_text(display_name, "display_name")
    user_id = _new_id("user")
    now = utc_now()
    with connect(db_path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO users (id, email, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, email, display_name, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise AppError(
                ErrorCode.USER_ALREADY_EXISTS,
                "A user with this email already exists.",
                {"email": email},
            ) from exc
        return _row_to_user(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def create_workspace(
    db_path: str,
    *,
    actor_id: str | None,
    name: str,
) -> dict[str, Any]:
    name = _ensure_text(name, "name")
    workspace_id = _new_id("workspace")
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        conn.execute(
            """
            INSERT INTO workspaces (id, name, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (workspace_id, name, actor_id, now, now),
        )
        return _row_to_workspace(_workspace_row(conn, workspace_id))


def list_workspaces(
    db_path: str,
    *,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_actor(conn, actor_id)
        rows = conn.execute(
            """
            SELECT DISTINCT workspaces.*
            FROM workspaces
            LEFT JOIN projects ON projects.workspace_id = workspaces.id
            LEFT JOIN project_members
                ON project_members.project_id = projects.id
               AND project_members.user_id = ?
            WHERE workspaces.owner_id = ?
               OR project_members.user_id IS NOT NULL
            ORDER BY workspaces.created_at ASC, workspaces.id ASC
            """,
            (actor_id, actor_id),
        ).fetchall()
        return {"workspaces": [_row_to_workspace(row) for row in rows]}


def get_workspace(
    db_path: str,
    *,
    workspace_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        return _row_to_workspace(
            _require_workspace_access(conn, workspace_id=workspace_id, actor_id=actor_id)
        )


def create_project(
    db_path: str,
    *,
    workspace_id: str,
    actor_id: str | None,
    name: str,
    description: str | None = None,
) -> dict[str, Any]:
    name = _ensure_text(name, "name")
    project_id = _new_id("project")
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_actor(conn, actor_id)
        workspace = _workspace_row(conn, workspace_id)
        if workspace["owner_id"] != actor_id:
            raise AppError(
                ErrorCode.PERMISSION_DENIED,
                "Only the workspace owner can create projects in this MVP.",
                {"actor_id": actor_id, "workspace_id": workspace_id},
            )
        conn.execute(
            """
            INSERT INTO projects (id, workspace_id, name, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, workspace_id, name, description, now, now),
        )
        conn.execute(
            """
            INSERT INTO project_members (id, project_id, user_id, role, created_at)
            VALUES (?, ?, ?, 'owner', ?)
            """,
            (_new_id("pm"), project_id, actor_id, now),
        )
        return _row_to_project(_project_row(conn, project_id), role="owner")


def list_workspace_projects(
    db_path: str,
    *,
    workspace_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        workspace = _require_workspace_access(conn, workspace_id=workspace_id, actor_id=actor_id)
        if workspace["owner_id"] == actor_id:
            rows = conn.execute(
                """
                SELECT projects.*, project_members.role
                FROM projects
                LEFT JOIN project_members
                    ON project_members.project_id = projects.id
                   AND project_members.user_id = ?
                WHERE projects.workspace_id = ?
                ORDER BY projects.created_at ASC, projects.id ASC
                """,
                (actor_id, workspace_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT projects.*, project_members.role
                FROM projects
                JOIN project_members ON project_members.project_id = projects.id
                WHERE projects.workspace_id = ? AND project_members.user_id = ?
                ORDER BY projects.created_at ASC, projects.id ASC
                """,
                (workspace_id, actor_id),
            ).fetchall()
        return {
            "workspace_id": workspace_id,
            "projects": [_row_to_project(row, role=row["role"]) for row in rows],
        }


def get_project(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = _project_row(conn, project_id)
        role = require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.DOCUMENT_READ,
        )
        return _row_to_project(row, role=role)


def list_project_members(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    with connect(db_path) as conn:
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.MEMBER_READ,
        )
        rows = conn.execute(
            """
            SELECT project_members.*,
                   users.email AS email,
                   users.display_name AS display_name
            FROM project_members
            JOIN users ON users.id = project_members.user_id
            WHERE project_members.project_id = ?
            ORDER BY
                CASE project_members.role
                    WHEN 'owner' THEN 1
                    WHEN 'admin' THEN 2
                    WHEN 'editor' THEN 3
                    WHEN 'reviewer' THEN 4
                    WHEN 'viewer' THEN 5
                    ELSE 99
                END,
                users.email ASC,
                project_members.id ASC
            """,
            (project_id,),
        ).fetchall()
        return {"project_id": project_id, "members": [_row_to_project_member(row) for row in rows]}


def add_project_member(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    user_id: str,
    role: str,
) -> dict[str, Any]:
    try:
        role = _ensure_role(role)
        now = utc_now()
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_project_permission(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission=ProjectPermission.MEMBER_MANAGE,
            )
            workspace_id = _project_workspace_id(conn, project_id)
            _user_row(conn, user_id)
            try:
                conn.execute(
                    """
                    INSERT INTO project_members (id, project_id, user_id, role, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (_new_id("pm"), project_id, user_id, role, now),
                )
            except sqlite3.IntegrityError as exc:
                raise AppError(
                    ErrorCode.PROJECT_MEMBER_ALREADY_EXISTS,
                    "User is already a project member.",
                    {"project_id": project_id, "user_id": user_id},
                ) from exc
            member = _row_to_project_member(_project_member_row(conn, project_id, user_id))
            record_audit_event(
                conn,
                actor_id=actor_id,
                workspace_id=workspace_id,
                project_id=project_id,
                action="project_member.add",
                target_type="project_member",
                target_id=user_id,
                outcome="success",
                details={
                    "project_id": project_id,
                    "target_user_id": user_id,
                    "role": role,
                    "member_id": member["id"],
                },
            )
            return member
    except AppError as exc:
        _record_project_member_audit_failure(
            db_path,
            action="project_member.add",
            project_id=project_id,
            actor_id=actor_id,
            user_id=user_id,
            role=role,
            error=exc,
        )
        raise


def update_project_member(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    user_id: str,
    role: str,
) -> dict[str, Any]:
    try:
        role = _ensure_role(role)
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_project_permission(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission=ProjectPermission.MEMBER_MANAGE,
            )
            workspace_id = _project_workspace_id(conn, project_id)
            member = _project_member_row(conn, project_id, user_id)
            previous_role = member["role"]
            _ensure_not_last_owner_change(
                conn,
                project_id=project_id,
                current_role=previous_role,
                next_role=role,
            )
            conn.execute(
                """
                UPDATE project_members
                SET role = ?
                WHERE project_id = ? AND user_id = ?
                """,
                (role, project_id, user_id),
            )
            updated = _row_to_project_member(_project_member_row(conn, project_id, user_id))
            record_audit_event(
                conn,
                actor_id=actor_id,
                workspace_id=workspace_id,
                project_id=project_id,
                action="project_member.update",
                target_type="project_member",
                target_id=user_id,
                outcome="success",
                details={
                    "project_id": project_id,
                    "target_user_id": user_id,
                    "previous_role": previous_role,
                    "role": role,
                    "member_id": updated["id"],
                },
            )
            return updated
    except AppError as exc:
        _record_project_member_audit_failure(
            db_path,
            action="project_member.update",
            project_id=project_id,
            actor_id=actor_id,
            user_id=user_id,
            role=role,
            error=exc,
        )
        raise


def remove_project_member(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    user_id: str,
) -> dict[str, Any]:
    try:
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_project_permission(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission=ProjectPermission.MEMBER_MANAGE,
            )
            workspace_id = _project_workspace_id(conn, project_id)
            member = _project_member_row(conn, project_id, user_id)
            removed_role = member["role"]
            _ensure_not_last_owner_change(
                conn,
                project_id=project_id,
                current_role=removed_role,
                next_role=None,
            )
            conn.execute(
                """
                DELETE FROM project_members
                WHERE project_id = ? AND user_id = ?
                """,
                (project_id, user_id),
            )
            result = {
                "project_id": project_id,
                "removed_user_id": user_id,
                "removed_member_id": member["id"],
            }
            record_audit_event(
                conn,
                actor_id=actor_id,
                workspace_id=workspace_id,
                project_id=project_id,
                action="project_member.remove",
                target_type="project_member",
                target_id=user_id,
                outcome="success",
                details={
                    "project_id": project_id,
                    "target_user_id": user_id,
                    "removed_role": removed_role,
                    "removed_member_id": member["id"],
                },
            )
            return result
    except AppError as exc:
        _record_project_member_audit_failure(
            db_path,
            action="project_member.remove",
            project_id=project_id,
            actor_id=actor_id,
            user_id=user_id,
            error=exc,
        )
        raise
