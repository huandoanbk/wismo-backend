"""OutboxEventEnvelope contract — outbox delivery envelope."""

from typing import Any

from pydantic import BaseModel

from wismo.contracts.enums import OutboxDeliveryState


class OutboxEventEnvelope(BaseModel):
    """Canonical envelope for outbox-dispatched events."""

    schema_version: str = "outbox.v1"
    idempotency_key: str
    event_type: str
    created_at: str  # ISO-8601 string
    delivery_state: OutboxDeliveryState = OutboxDeliveryState.PENDING
    dispatched_at: str | None = None  # ISO-8601 string
    payload: dict[str, Any] = {}
    attempt_count: int = 0
