from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import WebSocket

from app.errors import AppError


BROADCAST_SEND_TIMEOUT_SECONDS = 2.0
REDIS_CHANNEL = "openjson:collaboration"


class CollaborationHub:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._instance_id = uuid.uuid4().hex
        self._redis_url: str | None = None
        self._redis: Any = None
        self._redis_listener_task: asyncio.Task | None = None

    def configure(self, *, redis_url: str | None) -> None:
        self._redis_url = redis_url.strip() if redis_url else None

    async def start(self) -> None:
        if not self._redis_url or self._redis_listener_task is not None:
            return
        try:
            from redis import asyncio as redis_asyncio  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("OPENJSON_REDIS_URL requires the redis package.") from exc
        self._redis = redis_asyncio.from_url(self._redis_url, decode_responses=True)
        self._redis_listener_task = asyncio.create_task(self._listen_to_redis())

    async def stop(self) -> None:
        if self._redis_listener_task is not None:
            self._redis_listener_task.cancel()
            try:
                await self._redis_listener_task
            except asyncio.CancelledError:
                pass
            self._redis_listener_task = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def connect(self, document_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(document_id, set()).add(websocket)

    async def disconnect(self, document_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(document_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(document_id, None)

    async def broadcast(self, document_id: str, payload: dict[str, Any], *, publish_remote: bool = True) -> None:
        if publish_remote and self._redis is not None:
            await self._redis.publish(
                REDIS_CHANNEL,
                json.dumps(
                    {
                        "origin": self._instance_id,
                        "document_id": document_id,
                        "payload": payload,
                    },
                    separators=(",", ":"),
                ),
            )
        async with self._lock:
            sockets = list(self._connections.get(document_id, set()))
        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await asyncio.wait_for(
                    websocket.send_json(payload),
                    timeout=BROADCAST_SEND_TIMEOUT_SECONDS,
                )
            except (RuntimeError, asyncio.TimeoutError):
                stale.append(websocket)
        if stale:
            async with self._lock:
                active = self._connections.get(document_id)
                if active is not None:
                    for websocket in stale:
                        active.discard(websocket)
                    if not active:
                        self._connections.pop(document_id, None)

    async def broadcast_state(
        self,
        document_id: str,
        state: dict[str, Any],
        *,
        reason: str,
    ) -> None:
        await self.broadcast(
            document_id,
            {
                "type": "collaboration_state",
                "reason": reason,
                "state": state,
            },
        )

    async def _listen_to_redis(self) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(REDIS_CHANNEL)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    envelope = json.loads(message["data"])
                except json.JSONDecodeError:
                    continue
                if envelope.get("origin") == self._instance_id:
                    continue
                document_id = envelope.get("document_id")
                payload = envelope.get("payload")
                if isinstance(document_id, str) and isinstance(payload, dict):
                    await self.broadcast(document_id, payload, publish_remote=False)
        finally:
            await pubsub.unsubscribe(REDIS_CHANNEL)
            close = getattr(pubsub, "aclose", None)
            if close is not None:
                await close()
            else:
                await pubsub.close()


collaboration_hub = CollaborationHub()


def websocket_error_payload(error: AppError) -> dict[str, Any]:
    return {
        "type": "error",
        "error": error.as_response()["error"],
    }


def invalid_realtime_message(message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "error",
        "error": {
            "code": "INVALID_REQUEST",
            "message": message,
            "details": details or {},
        },
    }
