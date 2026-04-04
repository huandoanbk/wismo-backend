"""TracePayload contract — trace.v1 correlation envelope."""

from typing import Any

from pydantic import BaseModel


class TracePayload(BaseModel):
    """Canonical trace correlation payload for pipeline observability."""

    schema_version: str = "trace.v1"
    request_id: str
    turn_id: str | None = None
    session_id: str | None = None
    timestamps: dict[str, str] = {}
    latencies_ms: dict[str, int] = {}
    pipeline_steps: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
