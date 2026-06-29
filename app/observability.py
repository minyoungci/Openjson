from __future__ import annotations

import json
import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request


REQUEST_ID_HEADER = "X-Request-Id"


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def _json_log(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), flush=True)


def configure_request_observability(application: FastAPI, *, emit_logs: bool) -> None:
    @application.middleware("http")
    async def request_context_middleware(request: Request, call_next: Callable):
        request_id = request.headers.get(REQUEST_ID_HEADER) or _new_request_id()
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 3)
            if "response" in locals():
                response.headers[REQUEST_ID_HEADER] = request_id
            if emit_logs:
                _json_log(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "actor_id": request.headers.get("X-Actor-Id"),
                    }
                )
