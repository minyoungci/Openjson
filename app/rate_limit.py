from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.errors import AppError, ErrorCode


@dataclass(frozen=True)
class RateLimitConfig:
    enabled: bool
    requests: int
    window_seconds: int


class FixedWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._windows: dict[str, tuple[int, int]] = {}

    def check(self, key: str, *, now: float | None = None) -> dict[str, int | bool]:
        timestamp = now if now is not None else time.time()
        window_id = int(timestamp // self.window_seconds)
        count_window_id, count = self._windows.get(key, (window_id, 0))
        if count_window_id != window_id:
            count_window_id = window_id
            count = 0
        count += 1
        self._windows[key] = (count_window_id, count)
        reset_at = (window_id + 1) * self.window_seconds
        remaining = max(0, self.limit - count)
        return {
            "allowed": count <= self.limit,
            "limit": self.limit,
            "remaining": remaining,
            "reset_seconds": max(1, reset_at - int(timestamp)),
        }


def configure_rate_limiting(application: FastAPI, *, config: RateLimitConfig) -> None:
    application.state.rate_limit_config = config
    if not config.enabled:
        return

    limiter = FixedWindowRateLimiter(limit=config.requests, window_seconds=config.window_seconds)
    application.state.rate_limiter = limiter

    @application.middleware("http")
    async def rate_limit_middleware(request: Request, call_next: Callable):
        if _is_rate_limit_exempt(request.method, request.url.path):
            return await call_next(request)

        result = limiter.check(_rate_limit_key(request))
        if not result["allowed"]:
            app_error = AppError(
                ErrorCode.RATE_LIMITED,
                "Too many requests. Please retry after the rate limit window resets.",
                {
                    "limit": result["limit"],
                    "window_seconds": config.window_seconds,
                    "retry_after_seconds": result["reset_seconds"],
                },
            )
            response = JSONResponse(status_code=app_error.status_code, content=app_error.as_response())
        else:
            response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(result["limit"])
        response.headers["X-RateLimit-Remaining"] = str(result["remaining"])
        response.headers["X-RateLimit-Reset"] = str(result["reset_seconds"])
        if not result["allowed"]:
            response.headers["Retry-After"] = str(result["reset_seconds"])
        return response


def _is_rate_limit_exempt(method: str, path: str) -> bool:
    if method.upper() == "OPTIONS":
        return True
    return path in {"/health", "/ready"}


def _rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("Authorization")
    if authorization:
        return "auth:" + hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    actor_id = request.headers.get("X-Actor-Id")
    if actor_id:
        return "actor:" + actor_id
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return "ip:" + forwarded_for.split(",", 1)[0].strip()
    host = request.client.host if request.client else "unknown"
    return "ip:" + host


def rate_limit_config_from_env(
    *,
    enabled_raw: str | None,
    requests_raw: str | None,
    window_seconds_raw: str | None,
) -> RateLimitConfig:
    return RateLimitConfig(
        enabled=_env_flag(enabled_raw),
        requests=_positive_int(requests_raw, default=120),
        window_seconds=_positive_int(window_seconds_raw, default=60),
    )


def websocket_rate_limit_config_from_env(
    *,
    enabled_raw: str | None,
    messages_raw: str | None,
    window_seconds_raw: str | None,
) -> RateLimitConfig:
    return RateLimitConfig(
        enabled=_env_flag(enabled_raw),
        requests=_positive_int(messages_raw, default=120),
        window_seconds=_positive_int(window_seconds_raw, default=60),
    )


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
