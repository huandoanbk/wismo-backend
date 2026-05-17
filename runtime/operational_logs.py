"""Helpers for persisting operational diagnostics safely."""

from __future__ import annotations

import logging
from typing import Any

from runtime.models import OperationalLog

logger = logging.getLogger(__name__)


def record_operational_log(
    *,
    event_key: str,
    message: str,
    level: str = OperationalLog.LEVEL_ERROR,
    component: str = "",
    context: dict[str, Any] | None = None,
    turn=None,
) -> None:
    """Persist one operational log row without breaking runtime flow."""

    payload = context if isinstance(context, dict) else {}
    user = getattr(turn, "user", None) if turn is not None else None
    guest_identity = getattr(turn, "guest_identity", None) if turn is not None else None
    try:
        OperationalLog.objects.create(
            level=level,
            event_key=event_key,
            component=component,
            message=message,
            context=payload,
            turn=turn,
            user=user,
            guest_identity=guest_identity,
        )
    except Exception:
        logger.exception("operational_log_persist_failed")
