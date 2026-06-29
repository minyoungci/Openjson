from __future__ import annotations

import sqlite3

from app.errors import AppError, ErrorCode


class ProjectPermission:
    DOCUMENT_READ = "document:read"
    DOCUMENT_WRITE = "document:write"
    DOCUMENT_DELETE = "document:delete"
    DOCUMENT_RESTORE = "document:restore"
    DOCUMENT_ROLLBACK = "document:rollback"
    DOCUMENT_VALIDATE = "document:validate"
    SCHEMA_READ = "schema:read"
    SCHEMA_CREATE = "schema:create"
    COMMENT_READ = "comment:read"
    COMMENT_WRITE = "comment:write"
    REVIEW_READ = "review:read"
    REVIEW_CREATE = "review:create"
    REVIEW_DECIDE = "review:decide"
    REVIEW_APPLY = "review:apply"
    MEMBER_READ = "member:read"
    MEMBER_MANAGE = "member:manage"
    AUDIT_READ = "audit:read"
    EXPORT_READ = "export:read"
    INTEGRITY_READ = "integrity:read"


ROLE_PERMISSIONS = {
    "owner": {
        ProjectPermission.DOCUMENT_READ,
        ProjectPermission.DOCUMENT_WRITE,
        ProjectPermission.DOCUMENT_DELETE,
        ProjectPermission.DOCUMENT_RESTORE,
        ProjectPermission.DOCUMENT_ROLLBACK,
        ProjectPermission.DOCUMENT_VALIDATE,
        ProjectPermission.SCHEMA_READ,
        ProjectPermission.SCHEMA_CREATE,
        ProjectPermission.COMMENT_READ,
        ProjectPermission.COMMENT_WRITE,
        ProjectPermission.REVIEW_READ,
        ProjectPermission.REVIEW_CREATE,
        ProjectPermission.REVIEW_DECIDE,
        ProjectPermission.REVIEW_APPLY,
        ProjectPermission.MEMBER_READ,
        ProjectPermission.MEMBER_MANAGE,
        ProjectPermission.AUDIT_READ,
        ProjectPermission.EXPORT_READ,
        ProjectPermission.INTEGRITY_READ,
    },
    "admin": {
        ProjectPermission.DOCUMENT_READ,
        ProjectPermission.DOCUMENT_WRITE,
        ProjectPermission.DOCUMENT_DELETE,
        ProjectPermission.DOCUMENT_RESTORE,
        ProjectPermission.DOCUMENT_ROLLBACK,
        ProjectPermission.DOCUMENT_VALIDATE,
        ProjectPermission.SCHEMA_READ,
        ProjectPermission.SCHEMA_CREATE,
        ProjectPermission.COMMENT_READ,
        ProjectPermission.COMMENT_WRITE,
        ProjectPermission.REVIEW_READ,
        ProjectPermission.REVIEW_CREATE,
        ProjectPermission.REVIEW_DECIDE,
        ProjectPermission.REVIEW_APPLY,
        ProjectPermission.MEMBER_READ,
        ProjectPermission.MEMBER_MANAGE,
        ProjectPermission.AUDIT_READ,
        ProjectPermission.EXPORT_READ,
        ProjectPermission.INTEGRITY_READ,
    },
    "editor": {
        ProjectPermission.DOCUMENT_READ,
        ProjectPermission.DOCUMENT_WRITE,
        ProjectPermission.DOCUMENT_DELETE,
        ProjectPermission.DOCUMENT_ROLLBACK,
        ProjectPermission.DOCUMENT_VALIDATE,
        ProjectPermission.SCHEMA_READ,
        ProjectPermission.COMMENT_READ,
        ProjectPermission.COMMENT_WRITE,
        ProjectPermission.REVIEW_READ,
        ProjectPermission.REVIEW_CREATE,
        ProjectPermission.REVIEW_APPLY,
        ProjectPermission.MEMBER_READ,
    },
    "reviewer": {
        ProjectPermission.DOCUMENT_READ,
        ProjectPermission.DOCUMENT_VALIDATE,
        ProjectPermission.SCHEMA_READ,
        ProjectPermission.COMMENT_READ,
        ProjectPermission.COMMENT_WRITE,
        ProjectPermission.REVIEW_READ,
        ProjectPermission.REVIEW_DECIDE,
        ProjectPermission.MEMBER_READ,
    },
    "viewer": {
        ProjectPermission.DOCUMENT_READ,
        ProjectPermission.SCHEMA_READ,
        ProjectPermission.COMMENT_READ,
        ProjectPermission.REVIEW_READ,
        ProjectPermission.MEMBER_READ,
    },
}


def require_actor(conn: sqlite3.Connection, actor_id: str | None) -> None:
    if not actor_id:
        raise AppError(
            ErrorCode.AUTH_REQUIRED,
            "Request requires actor information.",
        )
    row = conn.execute("SELECT id FROM users WHERE id = ?", (actor_id,)).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.PERMISSION_DENIED,
            "Actor is not allowed to access this workspace.",
            {"actor_id": actor_id},
        )


def require_project_permission(
    conn: sqlite3.Connection,
    *,
    actor_id: str | None,
    project_id: str,
    permission: str,
) -> str:
    require_actor(conn, actor_id)
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise AppError(
            ErrorCode.PROJECT_NOT_FOUND,
            "Project not found.",
            {"project_id": project_id},
        )
    member = conn.execute(
        """
        SELECT role
        FROM project_members
        WHERE project_id = ? AND user_id = ?
        """,
        (project_id, actor_id),
    ).fetchone()
    if member is None:
        raise AppError(
            ErrorCode.PERMISSION_DENIED,
            "Actor is not a member of this project.",
            {"actor_id": actor_id, "project_id": project_id, "required_permission": permission},
        )
    role = member["role"]
    if permission not in ROLE_PERMISSIONS.get(role, set()):
        raise AppError(
            ErrorCode.PERMISSION_DENIED,
            "Actor role does not allow this operation.",
            {
                "actor_id": actor_id,
                "project_id": project_id,
                "role": role,
                "required_permission": permission,
            },
        )
    return role
