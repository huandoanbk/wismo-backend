"""WismoError contract — canonical error envelope."""

from typing import Any

from pydantic import BaseModel


class WismoError(BaseModel):
    """Canonical error contract for WISMO API responses."""

    schema_version: str = "error.v1"
    error_code: str
    error_category: str
    http_status: int
    frontend_state: str = "error"
    user_message: str
    retryable: bool = False
    request_id: str | None = None
    details: dict[str, Any] = {}
