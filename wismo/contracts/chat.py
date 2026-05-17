"""Dataclasses used by the MVP chat runtime foundation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ChatSendPayload:
    """Normalized user input accepted by the runtime orchestrator."""

    message: str
    chat_id: UUID | None = None
