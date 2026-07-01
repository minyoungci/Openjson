from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.errors import AppError, ErrorCode


DEFAULT_MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class RequestBodyLimitConfig:
    enabled: bool
    max_bytes: int


def configure_request_body_limiting(application: FastAPI, *, config: RequestBodyLimitConfig) -> None:
    application.state.request_body_limit_config = config
    if not config.enabled:
        return

    @application.middleware("http")
    async def request_body_limit_middleware(request: Request, call_next: Callable):
        if _is_bodyless_method(request.method):
            return await call_next(request)

        content_length = _parse_content_length(request.headers.get("content-length"))
        if content_length is not None and content_length > config.max_bytes:
            return _too_large_response(
                request_bytes=content_length,
                max_request_body_bytes=config.max_bytes,
            )

        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > config.max_bytes:
                return _too_large_response(
                    request_bytes=len(body) + len(chunk),
                    max_request_body_bytes=config.max_bytes,
                )
            body.extend(chunk)

        sent = False

        async def receive() -> dict:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        return await call_next(Request(request.scope, receive))


def request_body_limit_config_from_env(
    *,
    enabled_raw: str | None,
    max_bytes_raw: str | None,
) -> RequestBodyLimitConfig:
    return RequestBodyLimitConfig(
        enabled=_env_flag(enabled_raw),
        max_bytes=_positive_int(max_bytes_raw, default=DEFAULT_MAX_REQUEST_BODY_BYTES),
    )


def _too_large_response(*, request_bytes: int, max_request_body_bytes: int) -> JSONResponse:
    app_error = AppError(
        ErrorCode.REQUEST_BODY_TOO_LARGE,
        "Request body exceeds the configured size limit.",
        {
            "request_bytes": request_bytes,
            "max_request_body_bytes": max_request_body_bytes,
        },
    )
    return JSONResponse(status_code=app_error.status_code, content=app_error.as_response())


def _is_bodyless_method(method: str) -> bool:
    return method.upper() in {"GET", "HEAD", "OPTIONS"}


def _parse_content_length(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def _env_flag(raw: str | None) -> bool:
    return bool(raw and raw.strip().lower() in {"1", "true", "yes", "on"})


def _positive_int(raw: str | None, *, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)
