from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any

from app.auth_service import _new_id
from app.database import connect, utc_now


def send_invitation_email(
    db_path: str,
    *,
    invitation: dict[str, Any],
    token: str,
) -> dict[str, Any]:
    backend = (os.environ.get("OPENJSON_EMAIL_BACKEND") or "console").strip().lower()
    public_base_url = (os.environ.get("OPENJSON_PUBLIC_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    accept_url = f"{public_base_url}/app?invite_token={token}"
    subject = "OpenJson project invitation"
    body = (
        "You have been invited to an OpenJson project.\n\n"
        f"Project: {invitation['project_id']}\n"
        f"Role: {invitation['role']}\n"
        f"Accept invitation: {accept_url}\n"
    )
    status = "skipped"
    error_message = None
    attempted_at = utc_now()
    sent_at = None
    if backend == "disabled":
        status = "skipped"
    elif backend == "console":
        print(f"[OpenJson invitation email] to={invitation['email']} url={accept_url}")
        status = "sent"
        sent_at = utc_now()
    elif backend == "smtp":
        try:
            _send_smtp(to_email=invitation["email"], subject=subject, body=body)
            status = "sent"
            sent_at = utc_now()
        except Exception as exc:  # pragma: no cover - depends on external SMTP service
            status = "failed"
            error_message = str(exc)
    else:
        status = "failed"
        error_message = f"Unsupported email backend: {backend}"
    row = _record_email_delivery(
        db_path,
        invitation=invitation,
        backend=backend,
        status=status,
        error_message=error_message,
        attempted_at=attempted_at,
        sent_at=sent_at,
    )
    payload = _row_to_email_delivery(row)
    payload["accept_url"] = accept_url if status == "sent" and backend == "console" else None
    return payload


def _send_smtp(*, to_email: str, subject: str, body: str) -> None:
    host = _required_env("OPENJSON_SMTP_HOST")
    port = int(os.environ.get("OPENJSON_SMTP_PORT") or "587")
    sender = _required_env("OPENJSON_EMAIL_FROM")
    username = os.environ.get("OPENJSON_SMTP_USERNAME")
    password = os.environ.get("OPENJSON_SMTP_PASSWORD")
    use_tls = (os.environ.get("OPENJSON_SMTP_TLS") or "1").strip().lower() in {"1", "true", "yes", "on"}
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _record_email_delivery(
    db_path: str,
    *,
    invitation: dict[str, Any],
    backend: str,
    status: str,
    error_message: str | None,
    attempted_at: str,
    sent_at: str | None,
):
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        delivery_id = _new_id("email")
        conn.execute(
            """
            INSERT INTO email_deliveries (
                id,
                invitation_id,
                project_id,
                recipient_email,
                delivery_backend,
                status,
                error_message,
                created_at,
                attempted_at,
                sent_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                delivery_id,
                invitation["id"],
                invitation["project_id"],
                invitation["email"],
                backend,
                status,
                error_message,
                utc_now(),
                attempted_at,
                sent_at,
            ),
        )
        return conn.execute("SELECT * FROM email_deliveries WHERE id = ?", (delivery_id,)).fetchone()


def _row_to_email_delivery(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "invitation_id": row["invitation_id"],
        "project_id": row["project_id"],
        "recipient_email": row["recipient_email"],
        "delivery_backend": row["delivery_backend"],
        "status": row["status"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "attempted_at": row["attempted_at"],
        "sent_at": row["sent_at"],
    }
