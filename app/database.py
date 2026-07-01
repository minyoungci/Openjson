from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DB_PATH = os.environ.get(
    "OPENJSON_DB_PATH",
    str(Path.cwd() / "openjson.sqlite3"),
)

KNOWN_SCHEMA_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("0001_document_foundation", "Versioned JSON document foundation."),
    ("0002_schema_registry", "JSON Schema registry and validation schema references."),
    ("0003_project_rbac", "Project membership and role-based permission baseline."),
    ("0004_comments", "Document/path/event comment baseline."),
    ("0005_review_workflow", "Review request workflow baseline."),
    ("0006_workspace_project_api", "Workspace and project bootstrap API baseline."),
    ("0007_project_membership_management", "Project member management and owner protection."),
    ("0008_audit_log", "Append-only operational audit log baseline."),
    ("0009_deployment_baseline", "Health, readiness, Docker, and deployment smoke baseline."),
    ("0010_operations_baseline", "Request observability, replay check, and SQLite backup baseline."),
    ("0011_managed_migration_baseline", "Append-only schema migration ledger baseline."),
    ("0012_project_api_tokens", "Project-scoped API token authentication baseline."),
    ("0013_editor_presence", "Document editor presence and checkpoint monitoring baseline."),
    ("0014_sessions_invitations", "Password sessions and project invitations baseline."),
    ("0015_deployment_collaboration_auth_sync", "Collaborative text, email delivery, refresh tokens, OIDC, and offline sync baseline."),
    ("0016_document_snapshots", "Derived compacted document snapshot baseline."),
)


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workspaces_owner
ON workspaces(owner_id, created_at);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_workspace
ON projects(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS project_members (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'editor', 'reviewer', 'viewer')),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_project_members_user
ON project_members(user_id, project_id);

CREATE INDEX IF NOT EXISTS idx_project_members_project_role
ON project_members(project_id, role);

CREATE TABLE IF NOT EXISTS api_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    token_prefix TEXT NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_user_project
ON api_tokens(user_id, project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_api_tokens_project
ON api_tokens(project_id, created_at);

CREATE TABLE IF NOT EXISTS user_credentials (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    token_prefix TEXT NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user
ON user_sessions(user_id, created_at);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    session_id TEXT NOT NULL REFERENCES user_sessions(id),
    token_prefix TEXT NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    family_id TEXT NOT NULL,
    rotation_counter INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    revoked_at TEXT,
    replaced_by TEXT REFERENCES refresh_tokens(id)
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user
ON refresh_tokens(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_family
ON refresh_tokens(family_id, rotation_counter);

CREATE TABLE IF NOT EXISTS project_invitations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'editor', 'reviewer', 'viewer')),
    token_prefix TEXT NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    invited_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    accepted_by TEXT REFERENCES users(id),
    accepted_at TEXT,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_project_invitations_project
ON project_invitations(project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_project_invitations_email
ON project_invitations(email, project_id);

CREATE TABLE IF NOT EXISTS email_deliveries (
    id TEXT PRIMARY KEY,
    invitation_id TEXT REFERENCES project_invitations(id),
    project_id TEXT REFERENCES projects(id),
    recipient_email TEXT NOT NULL,
    delivery_backend TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('skipped', 'sent', 'failed')),
    error_message TEXT,
    created_at TEXT NOT NULL,
    attempted_at TEXT,
    sent_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_email_deliveries_invitation
ON email_deliveries(invitation_id, created_at);

CREATE TABLE IF NOT EXISTS oidc_states (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    state_hash TEXT UNIQUE NOT NULL,
    nonce TEXT NOT NULL,
    return_to TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS oidc_identities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(issuer, subject)
);

CREATE INDEX IF NOT EXISTS idx_oidc_identities_user
ON oidc_identities(user_id, issuer);

CREATE TABLE IF NOT EXISTS offline_sync_operations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    document_id TEXT NOT NULL REFERENCES json_documents(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    client_operation_id TEXT NOT NULL,
    operation_type TEXT NOT NULL CHECK (operation_type IN ('content_update')),
    base_version INTEGER NOT NULL,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('applied', 'conflict', 'failed')),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    applied_event_id TEXT REFERENCES document_events(id),
    applied_at TEXT,
    UNIQUE(actor_id, client_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_offline_sync_operations_project
ON offline_sync_operations(project_id, created_at);

CREATE TRIGGER IF NOT EXISTS trg_project_members_keep_owner_update
BEFORE UPDATE OF role ON project_members
WHEN OLD.role = 'owner'
 AND NEW.role <> 'owner'
 AND (
     SELECT COUNT(*)
     FROM project_members
     WHERE project_id = OLD.project_id AND role = 'owner'
 ) <= 1
BEGIN
    SELECT RAISE(ABORT, 'project must retain at least one owner');
END;

CREATE TRIGGER IF NOT EXISTS trg_project_members_keep_owner_delete
BEFORE DELETE ON project_members
WHEN OLD.role = 'owner'
 AND (
     SELECT COUNT(*)
     FROM project_members
     WHERE project_id = OLD.project_id AND role = 'owner'
 ) <= 1
BEGIN
    SELECT RAISE(ABORT, 'project must retain at least one owner');
END;

CREATE TABLE IF NOT EXISTS schemas (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    file_pattern TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, name, version)
);

CREATE TABLE IF NOT EXISTS json_documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    full_path TEXT NOT NULL,
    current_version INTEGER NOT NULL,
    current_snapshot_json TEXT NOT NULL,
    schema_id TEXT REFERENCES schemas(id),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_json_documents_active_path
ON json_documents(project_id, full_path)
WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS document_events (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES json_documents(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    validation_schema_id TEXT REFERENCES schemas(id),
    event_type TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    result_version INTEGER NOT NULL,
    patch TEXT NOT NULL,
    inverse_patch TEXT NOT NULL,
    changed_paths TEXT NOT NULL,
    before_values TEXT NOT NULL,
    after_values TEXT NOT NULL,
    summary TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(document_id, result_version)
);

CREATE INDEX IF NOT EXISTS idx_document_events_document_version
ON document_events(document_id, result_version);

CREATE TABLE IF NOT EXISTS document_snapshots (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES json_documents(id),
    version INTEGER NOT NULL CHECK (version > 0),
    snapshot_json TEXT NOT NULL,
    source_event_id TEXT NOT NULL REFERENCES document_events(id),
    created_at TEXT NOT NULL,
    UNIQUE(document_id, version),
    UNIQUE(source_event_id)
);

CREATE INDEX IF NOT EXISTS idx_document_snapshots_document_version
ON document_snapshots(document_id, version DESC);

CREATE TABLE IF NOT EXISTS editor_presence (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES json_documents(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN ('viewing', 'editing')),
    base_version INTEGER NOT NULL,
    dirty INTEGER NOT NULL DEFAULT 0,
    cursor_path TEXT,
    opened_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(document_id, actor_id)
);

CREATE INDEX IF NOT EXISTS idx_editor_presence_document_seen
ON editor_presence(document_id, last_seen_at);

CREATE TABLE IF NOT EXISTS comment_threads (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    document_id TEXT NOT NULL REFERENCES json_documents(id),
    anchor_type TEXT NOT NULL CHECK (anchor_type IN ('document', 'path', 'event')),
    anchor_path TEXT,
    anchor_event_id TEXT REFERENCES document_events(id),
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_by TEXT REFERENCES users(id),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_comment_threads_document
ON comment_threads(document_id, status, created_at);

CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES comment_threads(id),
    author_id TEXT NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comments_thread
ON comments(thread_id, created_at);

CREATE TABLE IF NOT EXISTS review_requests (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    author_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (status IN ('open', 'changes_requested', 'approved', 'applied', 'closed')),
    title TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    applied_by TEXT REFERENCES users(id),
    applied_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_review_requests_project_status
ON review_requests(project_id, status, created_at);

CREATE TABLE IF NOT EXISTS review_request_changes (
    id TEXT PRIMARY KEY,
    review_request_id TEXT NOT NULL REFERENCES review_requests(id),
    document_id TEXT NOT NULL REFERENCES json_documents(id),
    base_version INTEGER NOT NULL,
    patch TEXT NOT NULL,
    changed_paths TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(review_request_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_review_request_changes_request
ON review_request_changes(review_request_id);

CREATE TABLE IF NOT EXISTS review_decisions (
    id TEXT PRIMARY KEY,
    review_request_id TEXT NOT NULL REFERENCES review_requests(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    decision_type TEXT NOT NULL CHECK (decision_type IN ('approve', 'request_changes', 'comment')),
    body TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_decisions_request
ON review_decisions(review_request_id, created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    actor_id TEXT,
    workspace_id TEXT,
    project_id TEXT,
    document_id TEXT,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure')),
    error_code TEXT,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_project_created
ON audit_log(project_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_audit_log_actor_created
ON audit_log(actor_id, created_at, id);

CREATE TRIGGER IF NOT EXISTS trg_document_events_no_update
BEFORE UPDATE ON document_events
BEGIN
    SELECT RAISE(ABORT, 'document_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_document_events_no_delete
BEFORE DELETE ON document_events
BEGIN
    SELECT RAISE(ABORT, 'document_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_document_snapshots_no_update
BEFORE UPDATE ON document_snapshots
BEGIN
    SELECT RAISE(ABORT, 'document_snapshots are immutable derived artifacts');
END;

CREATE TRIGGER IF NOT EXISTS trg_document_snapshots_no_delete
BEFORE DELETE ON document_snapshots
BEGIN
    SELECT RAISE(ABORT, 'document_snapshots are immutable derived artifacts');
END;

CREATE TRIGGER IF NOT EXISTS trg_schemas_no_update
BEFORE UPDATE ON schemas
BEGIN
    SELECT RAISE(ABORT, 'schemas are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_schemas_no_delete
BEFORE DELETE ON schemas
BEGIN
    SELECT RAISE(ABORT, 'schemas are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_comments_no_update
BEFORE UPDATE ON comments
BEGIN
    SELECT RAISE(ABORT, 'comments are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_comments_no_delete
BEFORE DELETE ON comments
BEGIN
    SELECT RAISE(ABORT, 'comments are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_decisions_no_update
BEFORE UPDATE ON review_decisions
BEGIN
    SELECT RAISE(ABORT, 'review_decisions are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_decisions_no_delete
BEFORE DELETE ON review_decisions
BEGIN
    SELECT RAISE(ABORT, 'review_decisions are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_request_changes_no_update
BEFORE UPDATE ON review_request_changes
BEGIN
    SELECT RAISE(ABORT, 'review_request_changes are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_review_request_changes_no_delete
BEFORE DELETE ON review_request_changes
BEGIN
    SELECT RAISE(ABORT, 'review_request_changes are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_schema_migrations_no_update
BEFORE UPDATE ON schema_migrations
BEGIN
    SELECT RAISE(ABORT, 'schema_migrations is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_schema_migrations_no_delete
BEFORE DELETE ON schema_migrations
BEGIN
    SELECT RAISE(ABORT, 'schema_migrations is append-only');
END;
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DEFAULT_DB_PATH, factory=ManagedConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(json_documents)").fetchall()
        }
        if "schema_id" not in columns:
            conn.execute("ALTER TABLE json_documents ADD COLUMN schema_id TEXT REFERENCES schemas(id)")
        event_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(document_events)").fetchall()
        }
        if "validation_schema_id" not in event_columns:
            conn.execute("ALTER TABLE document_events ADD COLUMN validation_schema_id TEXT REFERENCES schemas(id)")
        _backfill_project_owner_memberships(conn)
        _record_known_schema_migrations(conn)


def get_schema_migration_status(db_path: str | None = None) -> dict[str, object]:
    expected_ids = [migration_id for migration_id, _ in KNOWN_SCHEMA_MIGRATIONS]
    with connect(db_path) as conn:
        table_exists = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_migrations'
            """
        ).fetchone()
        if table_exists is None:
            applied_rows = []
        else:
            applied_rows = conn.execute(
                """
                SELECT id, description, applied_at
                FROM schema_migrations
                ORDER BY applied_at ASC, id ASC
                """
            ).fetchall()
    applied = [
        {"id": row["id"], "description": row["description"], "applied_at": row["applied_at"]}
        for row in applied_rows
    ]
    applied_ids = {row["id"] for row in applied}
    expected_set = set(expected_ids)
    pending = [migration_id for migration_id in expected_ids if migration_id not in applied_ids]
    unknown = sorted(applied_ids - expected_set)
    if unknown:
        status = "drift"
    elif pending:
        status = "pending"
    else:
        status = "ok"
    return {
        "status": status,
        "current_schema_version": expected_ids[-1],
        "expected_migrations": expected_ids,
        "applied_migrations": applied,
        "applied_count": len(applied),
        "pending_migrations": pending,
        "unknown_migrations": unknown,
    }


def _record_known_schema_migrations(conn: sqlite3.Connection) -> None:
    now = utc_now()
    for migration_id, description in KNOWN_SCHEMA_MIGRATIONS:
        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (id, description, applied_at)
            VALUES (?, ?, ?)
            """,
            (migration_id, description, now),
        )


def _backfill_project_owner_memberships(conn: sqlite3.Connection) -> None:
    now = utc_now()
    rows = conn.execute(
        """
        SELECT projects.id AS project_id,
               workspaces.owner_id AS owner_id
        FROM projects
        JOIN workspaces ON workspaces.id = projects.workspace_id
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO project_members (id, project_id, user_id, role, created_at)
            VALUES (?, ?, ?, 'owner', ?)
            """,
            (f"pm_{row['project_id']}_{row['owner_id']}", row["project_id"], row["owner_id"], now),
        )
