from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.database import utc_now
from app.document_service import get_document_editor_state, update_document_content
from app.errors import AppError, ErrorCode


MAX_TEXT_OPERATION_LENGTH = 20_000
MAX_TEXT_SESSION_OPERATIONS = 1_000


@dataclass
class AcceptedTextOperation:
    server_revision: int
    base_revision: int
    actor_id: str
    client_id: str | None
    op: dict[str, Any]
    created_at: str


@dataclass
class TextSession:
    document_id: str
    document_version: int
    text: str
    revision: int = 0
    operations: list[AcceptedTextOperation] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now)


class TextCollaborationManager:
    def __init__(self) -> None:
        self._sessions: dict[str, TextSession] = {}
        self._lock = asyncio.Lock()

    async def join(self, db_path: str, *, document_id: str, actor_id: str) -> dict[str, Any]:
        editor_state = get_document_editor_state(
            db_path,
            document_id=document_id,
            actor_id=actor_id,
            include_validation=False,
            recent_events_limit=1,
        )
        document = editor_state["document"]
        async with self._lock:
            session = self._sessions.get(document_id)
            if session is None or (session.revision == 0 and session.document_version != document["current_version"]):
                session = TextSession(
                    document_id=document_id,
                    document_version=document["current_version"],
                    text=document["content_text"],
                )
                self._sessions[document_id] = session
            return self._session_payload(session)

    async def apply_operation(
        self,
        db_path: str,
        *,
        document_id: str,
        actor_id: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        await self.join(db_path, document_id=document_id, actor_id=actor_id)
        client_id = message.get("client_id")
        base_revision = _ensure_revision(message.get("base_text_revision"))
        incoming = _normalize_text_operation(message.get("op"))
        async with self._lock:
            session = self._require_session(document_id)
            if base_revision > session.revision:
                raise AppError(
                    ErrorCode.INVALID_REQUEST,
                    "base_text_revision cannot be ahead of the server text revision.",
                    {"base_text_revision": base_revision, "server_text_revision": session.revision},
                )
            transformed = dict(incoming)
            for accepted in session.operations:
                if accepted.server_revision > base_revision:
                    transformed = _transform_operation(transformed, accepted.op)
            session.text = _apply_text_operation(session.text, transformed)
            session.revision += 1
            accepted = AcceptedTextOperation(
                server_revision=session.revision,
                base_revision=base_revision,
                actor_id=actor_id,
                client_id=str(client_id) if client_id is not None else None,
                op=transformed,
                created_at=utc_now(),
            )
            session.operations.append(accepted)
            if len(session.operations) > MAX_TEXT_SESSION_OPERATIONS:
                session.operations = session.operations[-MAX_TEXT_SESSION_OPERATIONS:]
            session.updated_at = accepted.created_at
            return {
                "type": "text_session.op.accepted",
                "document_id": document_id,
                "document_version": session.document_version,
                "server_text_revision": session.revision,
                "base_text_revision": base_revision,
                "actor_id": actor_id,
                "client_id": accepted.client_id,
                "op": transformed,
                "created_at": accepted.created_at,
            }

    async def commit(
        self,
        db_path: str,
        *,
        document_id: str,
        actor_id: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        await self.join(db_path, document_id=document_id, actor_id=actor_id)
        expected_revision = message.get("text_revision")
        reason = message.get("reason") if isinstance(message.get("reason"), str) else "Committed collaborative text session"
        merge_strategy = message.get("merge_strategy") if isinstance(message.get("merge_strategy"), str) else "reject"
        async with self._lock:
            session = self._require_session(document_id)
            if expected_revision is not None and _ensure_revision(expected_revision) != session.revision:
                raise AppError(
                    ErrorCode.VERSION_CONFLICT,
                    "Text session revision conflict. Reload collaborative text session.",
                    {"client_text_revision": expected_revision, "server_text_revision": session.revision},
                )
            text = session.text
            base_version = session.document_version
            revision = session.revision
        result = update_document_content(
            db_path,
            document_id=document_id,
            actor_id=actor_id,
            base_version=base_version,
            content_text=text,
            content_text_provided=True,
            reason=reason,
            merge_strategy=merge_strategy,
        )
        editor_state = get_document_editor_state(
            db_path,
            document_id=document_id,
            actor_id=actor_id,
            include_validation=False,
            recent_events_limit=1,
        )
        async with self._lock:
            self._sessions[document_id] = TextSession(
                document_id=document_id,
                document_version=result["current_version"],
                text=editor_state["document"]["content_text"],
            )
        return {
            "type": "text_session.committed",
            "document_id": document_id,
            "text_revision": revision,
            "result_version": result["current_version"],
            "event_id": result["event_id"],
            "event_type": result["event_type"],
        }

    def _require_session(self, document_id: str) -> TextSession:
        session = self._sessions.get(document_id)
        if session is None:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "Text session has not been initialized.",
                {"document_id": document_id},
            )
        return session

    @staticmethod
    def _session_payload(session: TextSession) -> dict[str, Any]:
        return {
            "type": "text_session.state",
            "document_id": session.document_id,
            "document_version": session.document_version,
            "text_revision": session.revision,
            "content_text": session.text,
            "updated_at": session.updated_at,
        }


def _ensure_revision(value: Any) -> int:
    if not isinstance(value, int) or value < 0:
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "Text revision must be a non-negative integer.",
            {"value": value},
        )
    return value


def _normalize_text_operation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError(ErrorCode.INVALID_REQUEST, "Text operation must be an object.")
    op_type = value.get("type")
    if op_type == "insert":
        index = _ensure_index(value.get("index"))
        text = value.get("text")
        if not isinstance(text, str) or text == "":
            raise AppError(ErrorCode.INVALID_REQUEST, "Insert text must be a non-empty string.")
        if len(text) > MAX_TEXT_OPERATION_LENGTH:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "Insert text is too large.",
                {"max_length": MAX_TEXT_OPERATION_LENGTH},
            )
        return {"type": "insert", "index": index, "text": text}
    if op_type == "delete":
        index = _ensure_index(value.get("index"))
        length = value.get("length")
        if not isinstance(length, int) or length <= 0 or length > MAX_TEXT_OPERATION_LENGTH:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "Delete length must be a positive integer within the operation limit.",
                {"max_length": MAX_TEXT_OPERATION_LENGTH},
            )
        return {"type": "delete", "index": index, "length": length}
    if op_type == "replace":
        index = _ensure_index(value.get("index"))
        length = value.get("length")
        text = value.get("text")
        if not isinstance(length, int) or length <= 0 or length > MAX_TEXT_OPERATION_LENGTH:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "Replace length must be a positive integer within the operation limit.",
                {"max_length": MAX_TEXT_OPERATION_LENGTH},
            )
        if not isinstance(text, str) or len(text) > MAX_TEXT_OPERATION_LENGTH:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "Replace text must be a string within the operation limit.",
                {"max_length": MAX_TEXT_OPERATION_LENGTH},
            )
        return {"type": "replace", "index": index, "length": length, "text": text}
    raise AppError(
        ErrorCode.INVALID_REQUEST,
        "Unsupported text operation type.",
        {"type": op_type, "allowed": ["insert", "delete", "replace"]},
    )


def _ensure_index(value: Any) -> int:
    if not isinstance(value, int) or value < 0:
        raise AppError(ErrorCode.INVALID_REQUEST, "Text operation index must be a non-negative integer.", {"index": value})
    return value


def _transform_operation(incoming: dict[str, Any], accepted: dict[str, Any]) -> dict[str, Any]:
    transformed = dict(incoming)
    accepted_type = accepted["type"]
    incoming_type = transformed["type"]
    accepted_index = accepted["index"]
    incoming_index = transformed["index"]

    if accepted_type == "insert":
        accepted_length = len(accepted["text"])
        if incoming_index > accepted_index or (incoming_type == "insert" and incoming_index == accepted_index):
            transformed["index"] = incoming_index + accepted_length
    elif accepted_type == "delete":
        accepted_length = accepted["length"]
        accepted_end = accepted_index + accepted_length
        if incoming_index >= accepted_end:
            transformed["index"] = incoming_index - accepted_length
        elif incoming_index >= accepted_index:
            transformed["index"] = accepted_index
    elif accepted_type == "replace":
        removed_length = accepted["length"]
        inserted_length = len(accepted["text"])
        accepted_end = accepted_index + removed_length
        if incoming_index >= accepted_end:
            transformed["index"] = incoming_index - removed_length + inserted_length
        elif incoming_index >= accepted_index:
            transformed["index"] = accepted_index + inserted_length
    return transformed


def _apply_text_operation(text: str, op: dict[str, Any]) -> str:
    index = min(op["index"], len(text))
    if op["type"] == "insert":
        return text[:index] + op["text"] + text[index:]
    if op["type"] == "replace":
        length = min(op["length"], max(0, len(text) - index))
        return text[:index] + op["text"] + text[index + length :]
    length = min(op["length"], max(0, len(text) - index))
    return text[:index] + text[index + length :]


text_collaboration_manager = TextCollaborationManager()
