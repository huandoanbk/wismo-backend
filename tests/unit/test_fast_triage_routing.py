"""Regression tests for Step 4 fast triage / hard routing behavior."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from accounts.models import GuestIdentity
from accounts.services import GUEST_COOKIE_NAME
from admin_config.models import RuntimeConfig
from chat.models import ChatTurn
from consents.services import ConsentService
from runtime.models import UsageQuotaWindow
from runtime.services import QuotaService
from runtime.triage import TriageDecision, TriageResult

pytestmark = pytest.mark.django_db


def _client_with_guest(guest: GuestIdentity) -> APIClient:
    client = APIClient()
    client.cookies[GUEST_COOKIE_NAME] = str(guest.id)
    return client


def _parse_sse_stream(content: bytes) -> list[dict]:
    events: list[dict] = []
    for block in content.decode().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = ""
        data: dict = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        events.append({"type": event_type, "data": data})
    return events


def test_triage_crisis_branch_persists_safety_control_turn() -> None:
    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    RuntimeConfig.objects.update_or_create(
        key="runtime.step_trace",
        defaults={"value": {"level": "meta"}, "is_active": True},
    )
    client = _client_with_guest(guest)

    response = client.post("/api/chat/message/", {"message": "I want to kill myself"}, format="json")

    assert response.status_code == 200
    events = _parse_sse_stream(b"".join(response.streaming_content))
    assert [event["type"] for event in events] == ["response", "done"]

    response_event = events[0]["data"]
    done = events[1]["data"]
    assert response_event["response_key"] == "crisis_hotline_immediate"
    assert done["response_method"] == "CRISIS_SAFE_ONLY"
    assert done["turn_id"] is not None
    assert done["status"] == "completed"

    turn = ChatTurn.objects.get(id=done["turn_id"])
    assert turn.response_method == "CRISIS_SAFE_ONLY"
    assert turn.runtime_metadata["safety_control"] is True
    assert turn.runtime_metadata["response_key"] == "crisis_hotline_immediate"
    assert turn.runtime_metadata["exclude_from_memory_updates"] is True
    assert isinstance(turn.runtime_metadata.get("step_traces"), list)
    assert len(turn.runtime_metadata["step_traces"]) >= 3
    assert turn.runtime_metadata["step_traces"][0]["step"] == "step3_resolve_chat_context"
    assert turn.step12_finalization_status == "finalized"
    assert turn.usage_accounting_status == "finalized"


def test_triage_blocked_minor_branch_is_non_persist_with_null_turn_id() -> None:
    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    client = _client_with_guest(guest)

    response = client.post("/api/chat/message/", {"message": "I am 16 years old"}, format="json")

    assert response.status_code == 200
    events = _parse_sse_stream(b"".join(response.streaming_content))
    assert [event["type"] for event in events] == ["response", "done"]

    response_event = events[0]["data"]
    done = events[1]["data"]
    assert response_event["response_key"] == "blocked_minor"
    assert done["response_method"] == "BLOCKED_MINOR"
    assert done["turn_id"] is None
    assert done["status"] == "completed"
    assert done["chat_id"] is not None
    assert ChatTurn.objects.filter(guest_identity=guest).count() == 0


def test_triage_control_done_reflects_realtime_quota_exhaustion() -> None:
    """Control-path done event reflects current quota exhaustion after triage LLM consume."""

    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    UsageQuotaWindow.objects.create(
        guest_identity=guest,
        token_limit=1,
        used_tokens=0,
        is_exhausted=False,
    )
    client = _client_with_guest(guest)

    def _decide_blocked_minor(_self, *, chat, current_turn):  # noqa: ANN001
        _ = chat
        quota_service = QuotaService()
        window = quota_service.current_for_identity(guest_identity=current_turn.guest_identity)
        quota_service.consume_tokens(window, 1)
        return TriageResult(
            decision=TriageDecision.BLOCKED_MINOR,
            source="llm",
            reason_tags=["forced_blocked_minor"],
            confidence="high",
        )

    with patch(
        "runtime.triage.FastTriageService.decide",
        autospec=True,
        side_effect=_decide_blocked_minor,
    ):
        response = client.post("/api/chat/message/", {"message": "hello there"}, format="json")
        events = _parse_sse_stream(b"".join(response.streaming_content))

    assert response.status_code == 200
    done = events[-1]["data"]
    assert done["response_method"] == "BLOCKED_MINOR"
    assert done["quota_exhausted_after_turn"] is True
