from __future__ import annotations

import hashlib
import hmac
import base64
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from app.audit_service import record_audit_event
from app.database import connect, utc_now
from app.errors import AppError, ErrorCode
from app.permissions import ProjectPermission, require_project_permission


TOKEN_PREFIX = "ojt_"
SESSION_TOKEN_PREFIX = "ojs_"
REFRESH_TOKEN_PREFIX = "ojr_"
INVITATION_TOKEN_PREFIX = "oji_"
PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
SESSION_TTL_DAYS = 14
REFRESH_TTL_DAYS = 30
INVITATION_TTL_DAYS = 14
OIDC_STATE_TTL_MINUTES = 10
PROJECT_ROLES = {"owner", "admin", "editor", "reviewer", "viewer"}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _new_token_secret() -> str:
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def _new_session_secret() -> str:
    return f"{SESSION_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def _new_refresh_secret() -> str:
    return f"{REFRESH_TOKEN_PREFIX}{secrets.token_urlsafe(40)}"


def _new_invitation_secret() -> str:
    return f"{INVITATION_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


def _ensure_role(value: str | None) -> str:
    role = _ensure_text(value, "role")
    if role not in PROJECT_ROLES:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Project role is not supported.",
            {"role": role, "supported_roles": sorted(PROJECT_ROLES)},
        )
    return role


def _ensure_password(value: str | None) -> str:
    password = value or ""
    if len(password) < 8:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Password must be at least 8 characters.",
            {"field": "password", "min_length": 8},
        )
    return password


def _utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _future_timestamp(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def _future_timestamp_minutes(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    ).hex()
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt.hex()}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_raw, salt_hex, digest = stored.split("$", 3)
        iterations = int(iterations_raw)
    except (ValueError, TypeError):
        return False
    if algorithm != PASSWORD_ALGORITHM:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        iterations,
    ).hex()
    return hmac.compare_digest(candidate, digest)


def _row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_token(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "token_prefix": row["token_prefix"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
    }


def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "token_prefix": row["token_prefix"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
    }


def _row_to_refresh_token(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "session_id": row["session_id"],
        "token_prefix": row["token_prefix"],
        "family_id": row["family_id"],
        "rotation_counter": row["rotation_counter"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "used_at": row["used_at"],
        "revoked_at": row["revoked_at"],
        "replaced_by": row["replaced_by"],
    }


def _row_to_invitation(row: sqlite3.Row, *, include_token: str | None = None) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "project_id": row["project_id"],
        "email": row["email"],
        "role": row["role"],
        "token_prefix": row["token_prefix"],
        "invited_by": row["invited_by"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "accepted_by": row["accepted_by"],
        "accepted_at": row["accepted_at"],
        "revoked_at": row["revoked_at"],
    }
    if include_token is not None:
        payload["token"] = include_token
    return payload


def _create_session_and_refresh(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    family_id: str | None = None,
    rotation_counter: int = 0,
) -> dict[str, Any]:
    session_id = _new_id("sess")
    access_token = _new_session_secret()
    refresh_token = _new_refresh_secret()
    refresh_id = _new_id("rt")
    family_id = family_id or _new_id("rtfam")
    now = utc_now()
    conn.execute(
        """
        INSERT INTO user_sessions (
            id,
            user_id,
            token_prefix,
            token_hash,
            created_at,
            expires_at,
            last_used_at,
            revoked_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            session_id,
            user_id,
            access_token[:12],
            _hash_token(access_token),
            now,
            _future_timestamp(SESSION_TTL_DAYS),
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO refresh_tokens (
            id,
            user_id,
            session_id,
            token_prefix,
            token_hash,
            family_id,
            rotation_counter,
            created_at,
            expires_at,
            used_at,
            revoked_at,
            replaced_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
        """,
        (
            refresh_id,
            user_id,
            session_id,
            refresh_token[:12],
            _hash_token(refresh_token),
            family_id,
            rotation_counter,
            now,
            _future_timestamp(REFRESH_TTL_DAYS),
        ),
    )
    session_row = conn.execute("SELECT * FROM user_sessions WHERE id = ?", (session_id,)).fetchone()
    refresh_row = conn.execute("SELECT * FROM refresh_tokens WHERE id = ?", (refresh_id,)).fetchone()
    return {
        "session": _row_to_session(session_row),
        "token": access_token,
        "refresh": _row_to_refresh_token(refresh_row),
        "refresh_token": refresh_token,
    }


def _user_row(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.USER_NOT_FOUND,
            "User not found.",
            {"user_id": user_id},
        )
    return row


def _project_member_payload(conn: sqlite3.Connection, project_id: str, user_id: str) -> dict[str, Any]:
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
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "user_id": row["user_id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


def _project_workspace_id(conn: sqlite3.Connection, project_id: str) -> str | None:
    row = conn.execute("SELECT workspace_id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return None
    return row["workspace_id"]


def signup_with_password(
    db_path: str,
    *,
    email: str,
    display_name: str,
    password: str,
) -> dict[str, Any]:
    email = _ensure_email(email)
    display_name = _ensure_text(display_name, "display_name")
    password_hash = _hash_password(_ensure_password(password))
    user_id = _new_id("user")
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO users (id, email, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, email, display_name, now, now),
            )
            conn.execute(
                """
                INSERT INTO user_credentials (user_id, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, password_hash, now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise AppError(
                ErrorCode.USER_ALREADY_EXISTS,
                "A user with this email already exists.",
                {"email": email},
            ) from exc
        user = _row_to_user(_user_row(conn, user_id))
    session = login_with_password(db_path, email=email, password=password)
    return {
        "user": user,
        "session": session["session"],
        "token": session["token"],
        "refresh": session["refresh"],
        "refresh_token": session["refresh_token"],
    }


def login_with_password(
    db_path: str,
    *,
    email: str,
    password: str,
) -> dict[str, Any]:
    email = _ensure_email(email)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT users.*, user_credentials.password_hash
            FROM users
            JOIN user_credentials ON user_credentials.user_id = users.id
            WHERE users.email = ?
            """,
            (email,),
        ).fetchone()
        if row is None or not _verify_password(password, row["password_hash"]):
            raise AppError(
                ErrorCode.AUTH_REQUIRED,
                "Email or password is invalid.",
            )
        conn.execute("BEGIN IMMEDIATE")
        issued = _create_session_and_refresh(conn, user_id=row["id"])
        return {
            "user": _row_to_user(row),
            "session": issued["session"],
            "token": issued["token"],
            "refresh": issued["refresh"],
            "refresh_token": issued["refresh_token"],
        }


def refresh_session(db_path: str, *, refresh_token: str) -> dict[str, Any]:
    token_hash = _hash_token(_ensure_text(refresh_token, "refresh_token"))
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT refresh_tokens.*,
                   users.id AS user_id,
                   users.email AS email,
                   users.display_name AS display_name,
                   users.created_at AS user_created_at,
                   users.updated_at AS user_updated_at
            FROM refresh_tokens
            JOIN users ON users.id = refresh_tokens.user_id
            WHERE refresh_tokens.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if (
            row is None
            or not hmac.compare_digest(row["token_hash"], token_hash)
            or row["used_at"] is not None
            or row["revoked_at"] is not None
            or _utc_datetime(row["expires_at"]) <= datetime.now(timezone.utc)
        ):
            raise AppError(
                ErrorCode.AUTH_REQUIRED,
                "Refresh token is invalid, expired, or already used.",
            )
        issued = _create_session_and_refresh(
            conn,
            user_id=row["user_id"],
            family_id=row["family_id"],
            rotation_counter=row["rotation_counter"] + 1,
        )
        used_at = utc_now()
        conn.execute(
            """
            UPDATE refresh_tokens
            SET used_at = ?, replaced_by = ?
            WHERE id = ?
            """,
            (used_at, issued["refresh"]["id"], row["id"]),
        )
        conn.execute(
            """
            UPDATE user_sessions
            SET revoked_at = COALESCE(revoked_at, ?)
            WHERE id = ?
            """,
            (used_at, row["session_id"]),
        )
        return {
            "user": {
                "id": row["user_id"],
                "email": row["email"],
                "display_name": row["display_name"],
                "created_at": row["user_created_at"],
                "updated_at": row["user_updated_at"],
            },
            "session": issued["session"],
            "token": issued["token"],
            "refresh": issued["refresh"],
            "refresh_token": issued["refresh_token"],
        }


def validate_session_token(db_path: str, token: str) -> dict[str, str]:
    token_hash = _hash_token(token)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM user_sessions
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if (
            row is None
            or not hmac.compare_digest(row["token_hash"], token_hash)
            or row["revoked_at"] is not None
            or _utc_datetime(row["expires_at"]) <= datetime.now(timezone.utc)
        ):
            raise AppError(
                ErrorCode.AUTH_REQUIRED,
                "Session token is invalid, expired, or revoked.",
            )
        conn.execute(
            """
            UPDATE user_sessions
            SET last_used_at = ?
            WHERE id = ?
            """,
            (utc_now(), row["id"]),
        )
        return {"session_id": row["id"], "actor_id": row["user_id"]}


def logout_session(db_path: str, *, token: str) -> dict[str, Any]:
    token_hash = _hash_token(token)
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT *
            FROM user_sessions
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None or not hmac.compare_digest(row["token_hash"], token_hash):
            raise AppError(
                ErrorCode.AUTH_REQUIRED,
                "Session token is invalid.",
            )
        revoked_at = row["revoked_at"] or utc_now()
        if row["revoked_at"] is None:
            conn.execute(
                """
                UPDATE user_sessions
                SET revoked_at = ?
                WHERE id = ?
                """,
                (revoked_at, row["id"]),
            )
            conn.execute(
                """
                UPDATE refresh_tokens
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE session_id = ?
                """,
                (revoked_at, row["id"]),
            )
        revoked = conn.execute("SELECT * FROM user_sessions WHERE id = ?", (row["id"],)).fetchone()
        return {"session": _row_to_session(revoked)}


def get_current_session_user(db_path: str, *, actor_id: str | None) -> dict[str, Any]:
    if not actor_id:
        raise AppError(
            ErrorCode.AUTH_REQUIRED,
            "Request requires actor information.",
        )
    with connect(db_path) as conn:
        return {"user": _row_to_user(_user_row(conn, actor_id))}


def create_oidc_login_url(
    db_path: str,
    *,
    provider: str = "default",
    return_to: str | None = None,
) -> dict[str, Any]:
    config = _oidc_config(provider)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO oidc_states (id, provider, state_hash, nonce, return_to, created_at, expires_at, used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                _new_id("oidcstate"),
                provider,
                _hash_token(state),
                nonce,
                return_to,
                now,
                _future_timestamp_minutes(OIDC_STATE_TTL_MINUTES),
            ),
        )
    params = {
        "response_type": "code",
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "scope": config["scope"],
        "state": state,
        "nonce": nonce,
    }
    return {
        "provider": provider,
        "authorization_url": f"{config['authorization_endpoint']}?{urlencode(params)}",
        "expires_at": _future_timestamp_minutes(OIDC_STATE_TTL_MINUTES),
    }


def complete_oidc_callback(
    db_path: str,
    *,
    provider: str = "default",
    state: str,
    code: str,
) -> dict[str, Any]:
    config = _oidc_config(provider)
    state_hash = _hash_token(_ensure_text(state, "state"))
    code = _ensure_text(code, "code")
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        state_row = conn.execute(
            """
            SELECT *
            FROM oidc_states
            WHERE state_hash = ? AND provider = ?
            """,
            (state_hash, provider),
        ).fetchone()
        if (
            state_row is None
            or state_row["used_at"] is not None
            or _utc_datetime(state_row["expires_at"]) <= datetime.now(timezone.utc)
        ):
            raise AppError(ErrorCode.AUTH_REQUIRED, "OIDC state is invalid or expired.")
        conn.execute("UPDATE oidc_states SET used_at = ? WHERE id = ?", (utc_now(), state_row["id"]))
    token_payload = _exchange_oidc_code(config, code)
    claims = _oidc_claims(config, token_payload, nonce=state_row["nonce"])
    email = _ensure_email(claims.get("email"))
    subject = _ensure_text(claims.get("sub"), "sub")
    issuer = _ensure_text(claims.get("iss") or config["issuer"], "iss")
    display_name = str(claims.get("name") or email)
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        identity = conn.execute(
            """
            SELECT oidc_identities.*, users.email AS user_email, users.display_name
            FROM oidc_identities
            JOIN users ON users.id = oidc_identities.user_id
            WHERE oidc_identities.issuer = ? AND oidc_identities.subject = ?
            """,
            (issuer, subject),
        ).fetchone()
        if identity is None:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user is None:
                user_id = _new_id("user")
                conn.execute(
                    """
                    INSERT INTO users (id, email, display_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, email, display_name, now, now),
                )
            else:
                user_id = user["id"]
            conn.execute(
                """
                INSERT INTO oidc_identities (id, user_id, issuer, subject, email, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (_new_id("oidc"), user_id, issuer, subject, email, now, now),
            )
        else:
            user_id = identity["user_id"]
            conn.execute(
                """
                UPDATE oidc_identities
                SET email = ?, updated_at = ?
                WHERE id = ?
                """,
                (email, now, identity["id"]),
            )
        issued = _create_session_and_refresh(conn, user_id=user_id)
        user_row = _user_row(conn, user_id)
        return {
            "user": _row_to_user(user_row),
            "session": issued["session"],
            "token": issued["token"],
            "refresh": issued["refresh"],
            "refresh_token": issued["refresh_token"],
            "return_to": state_row["return_to"],
        }


def _oidc_config(provider: str) -> dict[str, str]:
    suffix = "" if provider == "default" else f"_{provider.upper()}"
    issuer = os.environ.get(f"OPENJSON_OIDC_ISSUER{suffix}") or os.environ.get("OPENJSON_OIDC_ISSUER")
    client_id = os.environ.get(f"OPENJSON_OIDC_CLIENT_ID{suffix}") or os.environ.get("OPENJSON_OIDC_CLIENT_ID")
    client_secret = os.environ.get(f"OPENJSON_OIDC_CLIENT_SECRET{suffix}") or os.environ.get("OPENJSON_OIDC_CLIENT_SECRET")
    redirect_uri = os.environ.get(f"OPENJSON_OIDC_REDIRECT_URI{suffix}") or os.environ.get("OPENJSON_OIDC_REDIRECT_URI")
    authorization_endpoint = os.environ.get(f"OPENJSON_OIDC_AUTHORIZATION_ENDPOINT{suffix}") or os.environ.get(
        "OPENJSON_OIDC_AUTHORIZATION_ENDPOINT"
    )
    token_endpoint = os.environ.get(f"OPENJSON_OIDC_TOKEN_ENDPOINT{suffix}") or os.environ.get("OPENJSON_OIDC_TOKEN_ENDPOINT")
    jwks_uri = os.environ.get(f"OPENJSON_OIDC_JWKS_URI{suffix}") or os.environ.get("OPENJSON_OIDC_JWKS_URI")
    userinfo_endpoint = os.environ.get(f"OPENJSON_OIDC_USERINFO_ENDPOINT{suffix}") or os.environ.get(
        "OPENJSON_OIDC_USERINFO_ENDPOINT"
    )
    scope = os.environ.get(f"OPENJSON_OIDC_SCOPE{suffix}") or os.environ.get("OPENJSON_OIDC_SCOPE") or "openid email profile"
    missing = [
        name
        for name, value in {
            "issuer": issuer,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "authorization_endpoint": authorization_endpoint,
            "token_endpoint": token_endpoint,
        }.items()
        if not value
    ]
    if missing:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "OIDC provider is not configured.",
            {"provider": provider, "missing": missing},
        )
    return {
        "issuer": issuer,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "jwks_uri": jwks_uri or "",
        "userinfo_endpoint": userinfo_endpoint or "",
        "scope": scope,
    }


def _exchange_oidc_code(config: dict[str, str], code: str) -> dict[str, Any]:
    import httpx

    response = httpx.post(
        config["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config["redirect_uri"],
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
        },
        timeout=10,
    )
    if response.status_code >= 400:
        raise AppError(
            ErrorCode.AUTH_REQUIRED,
            "OIDC token exchange failed.",
            {"status_code": response.status_code},
        )
    return response.json()


def _oidc_claims(config: dict[str, str], token_payload: dict[str, Any], *, nonce: str) -> dict[str, Any]:
    id_token = token_payload.get("id_token")
    if isinstance(id_token, str) and config["jwks_uri"]:
        try:
            import jwt

            signing_key = jwt.PyJWKClient(config["jwks_uri"]).get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=config["client_id"],
                issuer=config["issuer"],
            )
        except Exception as exc:
            raise AppError(ErrorCode.AUTH_REQUIRED, "OIDC id_token verification failed.", {"message": str(exc)}) from exc
    elif isinstance(id_token, str):
        claims = _decode_unverified_jwt_payload(id_token)
        audience = claims.get("aud")
        audience_matches = audience == config["client_id"] or (
            isinstance(audience, list) and config["client_id"] in audience
        )
        if claims.get("iss") != config["issuer"] or not audience_matches:
            raise AppError(ErrorCode.AUTH_REQUIRED, "OIDC id_token claims are invalid.")
    else:
        claims = {}
    if claims and claims.get("nonce") not in {None, nonce}:
        raise AppError(ErrorCode.AUTH_REQUIRED, "OIDC nonce is invalid.")
    if config["userinfo_endpoint"] and token_payload.get("access_token"):
        import httpx

        response = httpx.get(
            config["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {token_payload['access_token']}"},
            timeout=10,
        )
        if response.status_code < 400:
            claims.update(response.json())
    return claims


def _decode_unverified_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        raise AppError(ErrorCode.AUTH_REQUIRED, "OIDC id_token is malformed.")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))


def create_project_invitation(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    email: str,
    role: str,
) -> dict[str, Any]:
    email = _ensure_email(email)
    role = _ensure_role(role)
    invitation_id = _new_id("invite")
    token = _new_invitation_secret()
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        require_project_permission(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            permission=ProjectPermission.MEMBER_MANAGE,
        )
        conn.execute(
            """
            INSERT INTO project_invitations (
                id,
                project_id,
                email,
                role,
                token_prefix,
                token_hash,
                invited_by,
                created_at,
                expires_at,
                accepted_by,
                accepted_at,
                revoked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
            """,
            (
                invitation_id,
                project_id,
                email,
                role,
                token[:12],
                _hash_token(token),
                actor_id,
                now,
                _future_timestamp(INVITATION_TTL_DAYS),
            ),
        )
        record_audit_event(
            conn,
            actor_id=actor_id,
            workspace_id=_project_workspace_id(conn, project_id),
            project_id=project_id,
            action="project_invitation.create",
            target_type="project_invitation",
            target_id=invitation_id,
            outcome="success",
            details={"project_id": project_id, "email": email, "role": role},
        )
        row = conn.execute("SELECT * FROM project_invitations WHERE id = ?", (invitation_id,)).fetchone()
        return _row_to_invitation(row, include_token=token)


def list_project_invitations(
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
            permission=ProjectPermission.MEMBER_MANAGE,
        )
        rows = conn.execute(
            """
            SELECT *
            FROM project_invitations
            WHERE project_id = ?
            ORDER BY created_at DESC, id ASC
            """,
            (project_id,),
        ).fetchall()
        return {"project_id": project_id, "invitations": [_row_to_invitation(row) for row in rows]}


def accept_project_invitation(
    db_path: str,
    *,
    token: str,
    actor_id: str | None,
) -> dict[str, Any]:
    token_hash = _hash_token(_ensure_text(token, "token"))
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        user = _user_row(conn, actor_id) if actor_id else None
        if user is None:
            raise AppError(
                ErrorCode.AUTH_REQUIRED,
                "Accepting an invitation requires an authenticated user.",
            )
        invitation = conn.execute(
            """
            SELECT *
            FROM project_invitations
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if (
            invitation is None
            or not hmac.compare_digest(invitation["token_hash"], token_hash)
            or invitation["revoked_at"] is not None
            or invitation["accepted_at"] is not None
            or _utc_datetime(invitation["expires_at"]) <= datetime.now(timezone.utc)
        ):
            raise AppError(
                ErrorCode.AUTH_REQUIRED,
                "Invitation token is invalid, expired, or already used.",
            )
        if user["email"] != invitation["email"]:
            raise AppError(
                ErrorCode.PERMISSION_DENIED,
                "Invitation email does not match the authenticated user.",
                {"invitation_email": invitation["email"], "user_email": user["email"]},
            )
        member = conn.execute(
            """
            SELECT id
            FROM project_members
            WHERE project_id = ? AND user_id = ?
            """,
            (invitation["project_id"], user["id"]),
        ).fetchone()
        if member is None:
            conn.execute(
                """
                INSERT INTO project_members (id, project_id, user_id, role, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _new_id("pm"),
                    invitation["project_id"],
                    user["id"],
                    invitation["role"],
                    utc_now(),
                ),
            )
            record_audit_event(
                conn,
                actor_id=user["id"],
                workspace_id=_project_workspace_id(conn, invitation["project_id"]),
                project_id=invitation["project_id"],
                action="project_invitation.accept",
                target_type="project_invitation",
                target_id=invitation["id"],
                outcome="success",
                details={
                    "project_id": invitation["project_id"],
                    "invitation_id": invitation["id"],
                    "role": invitation["role"],
                },
            )
        accepted_at = utc_now()
        conn.execute(
            """
            UPDATE project_invitations
            SET accepted_by = ?, accepted_at = ?
            WHERE id = ?
            """,
            (user["id"], accepted_at, invitation["id"]),
        )
        accepted = conn.execute("SELECT * FROM project_invitations WHERE id = ?", (invitation["id"],)).fetchone()
        return {
            "invitation": _row_to_invitation(accepted),
            "member": _project_member_payload(conn, invitation["project_id"], user["id"]),
        }


def _record_api_token_audit_failure(
    db_path: str,
    *,
    action: str,
    project_id: str,
    actor_id: str | None,
    token_id: str,
    error: AppError,
    name: str | None = None,
    token_prefix: str | None = None,
) -> None:
    details: dict[str, Any] = {
        "project_id": project_id,
        "token_id": token_id,
        "error_details": error.details,
    }
    if name is not None:
        details["name"] = name
    if token_prefix is not None:
        details["token_prefix"] = token_prefix
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        record_audit_event(
            conn,
            actor_id=actor_id,
            workspace_id=_project_workspace_id(conn, project_id),
            project_id=project_id,
            action=action,
            target_type="api_token",
            target_id=token_id,
            outcome="failure",
            error_code=error.code,
            details=details,
        )


def create_project_api_token(
    db_path: str,
    *,
    project_id: str,
    actor_id: str | None,
    name: str,
) -> dict[str, Any]:
    name = _ensure_text(name, "name")
    token_id = _new_id("tok")
    token_secret = _new_token_secret()
    token_prefix = token_secret[:12]
    token_hash = _hash_token(token_secret)
    now = utc_now()
    try:
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_project_permission(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission=ProjectPermission.DOCUMENT_READ,
            )
            conn.execute(
                """
                INSERT INTO api_tokens (
                    id,
                    user_id,
                    project_id,
                    name,
                    token_prefix,
                    token_hash,
                    created_at,
                    last_used_at,
                    revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (token_id, actor_id, project_id, name, token_prefix, token_hash, now),
            )
            record_audit_event(
                conn,
                actor_id=actor_id,
                workspace_id=_project_workspace_id(conn, project_id),
                project_id=project_id,
                action="api_token.create",
                target_type="api_token",
                target_id=token_id,
                outcome="success",
                details={
                    "project_id": project_id,
                    "token_id": token_id,
                    "name": name,
                    "token_prefix": token_prefix,
                },
            )
            row = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (token_id,)).fetchone()
            payload = _row_to_token(row)
            payload["token"] = token_secret
            return payload
    except AppError as exc:
        _record_api_token_audit_failure(
            db_path,
            action="api_token.create",
            project_id=project_id,
            actor_id=actor_id,
            token_id=token_id,
            name=name,
            token_prefix=token_prefix,
            error=exc,
        )
        raise


def list_project_api_tokens(
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
            permission=ProjectPermission.DOCUMENT_READ,
        )
        rows = conn.execute(
            """
            SELECT *
            FROM api_tokens
            WHERE project_id = ? AND user_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (project_id, actor_id),
        ).fetchall()
        return {"project_id": project_id, "api_tokens": [_row_to_token(row) for row in rows]}


def revoke_project_api_token(
    db_path: str,
    *,
    project_id: str,
    token_id: str,
    actor_id: str | None,
) -> dict[str, Any]:
    token_prefix = None
    try:
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_project_permission(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission=ProjectPermission.DOCUMENT_READ,
            )
            row = conn.execute(
                """
                SELECT *
                FROM api_tokens
                WHERE id = ? AND project_id = ? AND user_id = ?
                """,
                (token_id, project_id, actor_id),
            ).fetchone()
            if row is None:
                raise AppError(
                    ErrorCode.API_TOKEN_NOT_FOUND,
                    "API token not found.",
                    {"project_id": project_id, "token_id": token_id},
                )
            token_prefix = row["token_prefix"]
            revoked_at = row["revoked_at"] or utc_now()
            if row["revoked_at"] is None:
                conn.execute(
                    """
                    UPDATE api_tokens
                    SET revoked_at = ?
                    WHERE id = ?
                    """,
                    (revoked_at, token_id),
                )
                record_audit_event(
                    conn,
                    actor_id=actor_id,
                    workspace_id=_project_workspace_id(conn, project_id),
                    project_id=project_id,
                    action="api_token.revoke",
                    target_type="api_token",
                    target_id=token_id,
                    outcome="success",
                    details={
                        "project_id": project_id,
                        "token_id": token_id,
                        "token_prefix": row["token_prefix"],
                    },
                )
            revoked = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (token_id,)).fetchone()
            return _row_to_token(revoked)
    except AppError as exc:
        _record_api_token_audit_failure(
            db_path,
            action="api_token.revoke",
            project_id=project_id,
            actor_id=actor_id,
            token_id=token_id,
            token_prefix=token_prefix,
            error=exc,
        )
        raise


def parse_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise AppError(
            ErrorCode.AUTH_REQUIRED,
            "Authorization header must use Bearer token format.",
        )
    return value.strip()


def validate_api_token(db_path: str, token: str) -> dict[str, str]:
    token_hash = _hash_token(token)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM api_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None or not hmac.compare_digest(row["token_hash"], token_hash) or row["revoked_at"] is not None:
            raise AppError(
                ErrorCode.AUTH_REQUIRED,
                "API token is invalid or revoked.",
            )
        conn.execute(
            """
            UPDATE api_tokens
            SET last_used_at = ?
            WHERE id = ?
            """,
            (utc_now(), row["id"]),
        )
        return {"token_id": row["id"], "actor_id": row["user_id"], "project_id": row["project_id"]}


def authenticate_bearer_token(db_path: str, token: str) -> dict[str, str]:
    if token.startswith(SESSION_TOKEN_PREFIX):
        return {"token_type": "session", **validate_session_token(db_path, token)}
    if token.startswith(TOKEN_PREFIX):
        return {"token_type": "api_token", **validate_api_token(db_path, token)}
    try:
        return {"token_type": "api_token", **validate_api_token(db_path, token)}
    except AppError:
        return {"token_type": "session", **validate_session_token(db_path, token)}


def enforce_api_token_scope(db_path: str, *, token_project_id: str, method: str, path: str) -> None:
    if method.upper() == "OPTIONS":
        return
    if path in {"/health", "/ready"} or (method.upper() == "POST" and path == "/users"):
        return
    known_project_context, request_project_id = _request_project_context(db_path, path)
    if known_project_context and request_project_id is None:
        return
    if not known_project_context:
        raise AppError(
            ErrorCode.PERMISSION_DENIED,
            "Project-scoped API token cannot access this endpoint.",
            {"token_project_id": token_project_id, "path": path},
        )
    if request_project_id != token_project_id:
        raise AppError(
            ErrorCode.PERMISSION_DENIED,
            "Project-scoped API token cannot access another project.",
            {"token_project_id": token_project_id, "request_project_id": request_project_id},
        )


def _request_project_context(db_path: str, path: str) -> tuple[bool, str | None]:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return False, None
    resource = parts[0]
    if resource == "projects" and len(parts) >= 2:
        return True, parts[1]
    if resource == "documents" and len(parts) >= 2:
        return True, _lookup_project_id(db_path, "json_documents", parts[1])
    if resource == "schemas" and len(parts) >= 2:
        return True, _lookup_project_id(db_path, "schemas", parts[1])
    if resource == "comment-threads" and len(parts) >= 2:
        return True, _lookup_project_id(db_path, "comment_threads", parts[1])
    if resource == "review-requests" and len(parts) >= 2:
        return True, _lookup_project_id(db_path, "review_requests", parts[1])
    return False, None


def _lookup_project_id(db_path: str, table: str, resource_id: str) -> str | None:
    with connect(db_path) as conn:
        row = conn.execute(f"SELECT project_id FROM {table} WHERE id = ?", (resource_id,)).fetchone()
        if row is None:
            return None
        return row["project_id"]
