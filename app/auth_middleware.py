from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth_service import authenticate_bearer_token, enforce_api_token_scope, parse_bearer_token
from app.errors import AppError, ErrorCode


def configure_api_token_authentication(
    application: FastAPI,
    *,
    db_path: str,
    allow_actor_header: bool = True,
) -> None:
    @application.middleware("http")
    async def api_token_auth_middleware(request: Request, call_next: Callable):
        try:
            bearer_token = parse_bearer_token(request.headers.get("Authorization"))
            header_actor_id = request.headers.get("X-Actor-Id")
            if bearer_token is not None:
                token_context = authenticate_bearer_token(db_path, bearer_token)
                if header_actor_id is not None and header_actor_id != token_context["actor_id"]:
                    raise AppError(
                        ErrorCode.PERMISSION_DENIED,
                        "X-Actor-Id does not match bearer token actor.",
                        {"actor_id": header_actor_id},
                    )
                if token_context["token_type"] == "api_token":
                    enforce_api_token_scope(
                        db_path,
                        token_project_id=token_context["project_id"],
                        method=request.method,
                        path=request.url.path,
                    )
                _set_actor_header(request, token_context["actor_id"])
            elif header_actor_id is not None and not allow_actor_header and not _is_public_request(
                request.method,
                request.url.path,
            ):
                raise AppError(
                    ErrorCode.AUTH_REQUIRED,
                    "Bearer token authentication is required.",
                    {"actor_header_allowed": False},
                )
            return await call_next(request)
        except AppError as exc:
            return JSONResponse(status_code=exc.status_code, content=exc.as_response())


def _set_actor_header(request: Request, actor_id: str) -> None:
    headers = [
        (name, value)
        for name, value in request.scope["headers"]
        if name.lower() != b"x-actor-id"
    ]
    headers.append((b"x-actor-id", actor_id.encode("utf-8")))
    request.scope["headers"] = headers
    if hasattr(request, "_headers"):
        delattr(request, "_headers")


def _is_public_request(method: str, path: str) -> bool:
    upper_method = method.upper()
    if upper_method == "OPTIONS":
        return True
    if path in {"/", "/app", "/favicon.ico", "/health", "/ready", "/version"}:
        return True
    if path.startswith("/static/"):
        return True
    if upper_method == "GET" and path == "/auth/oidc/login":
        return True
    if upper_method == "POST" and path in {
        "/users",
        "/auth/signup",
        "/auth/login",
        "/auth/refresh",
        "/auth/oidc/callback",
    }:
        return True
    return False
