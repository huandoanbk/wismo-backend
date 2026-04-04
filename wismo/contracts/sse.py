"""SSE contracts — SSEEvent, ChatDonePayload, ChatSendRequest."""

from typing import Any

from pydantic import BaseModel, Field


class SSEEvent(BaseModel):
    """Canonical payload for a single SSE stream event."""

    schema_version: str = "sse.v1"
    type: str
    request_id: str
    data: dict[str, Any] = {}
    sequence: int | None = None


class ChatDonePayload(BaseModel):
    """Payload for the canonical SSE 'done' event."""

    schema_version: str = "chat-done.v1"
    request_id: str
    session_id: str
    final_text: str
    turn_id: str | None = None
    latency_ms: int | None = None
    safety_state: str | None = None


class ChatSendRequest(BaseModel):
    """Canonical request body for sending a chat message."""

    schema_version: str = "chat-send.v1"
    content: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    request_id: str | None = None
