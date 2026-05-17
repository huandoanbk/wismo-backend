"""Runtime config and quota foundation regression tests."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import GuestIdentity
from accounts.services import GUEST_COOKIE_NAME
from admin_config.models import RuntimeConfig
from chat.models import ChatTurn
from consents.services import ConsentService
from runtime.models import UsageQuotaWindow
from runtime.request_gate import RequestGatePipeline
from runtime.services import (
    PendingInputLimits,
    QuotaPolicy,
    QuotaService,
    RuntimeConfigService,
    RuntimeInputLimits,
    StepTraceConfig,
)

pytestmark = pytest.mark.django_db


def parse_sse_stream(content: bytes) -> list[dict]:
    """Parse SSE response bytes into a list of {type, data} dicts."""

    events = []
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
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    pass
        if event_type:
            events.append({"type": event_type, "data": data})
    return events


def api_client_with_guest(guest: GuestIdentity) -> APIClient:
    """Return an API client carrying the guest cookie."""

    client = APIClient()
    client.cookies[GUEST_COOKIE_NAME] = str(guest.id)
    return client


def test_runtime_config_service_reads_active_values_and_defaults() -> None:
    """Runtime config lookup returns canonical defaults and active overrides."""

    service = RuntimeConfigService()

    assert service.input_limits() == RuntimeInputLimits(max_message_length_chars=8000, max_payload_bytes=65536)
    assert service.guest_quota_policy() == QuotaPolicy(token_limit=100000, window_seconds=86400)
    assert service.user_quota_policy() == QuotaPolicy(token_limit=1000000, window_seconds=86400)
    assert service.pending_input_limits() == PendingInputLimits(max_appends=10, max_chars=12000)
    assert service.step_trace_config() == StepTraceConfig(level="off")

    RuntimeConfig.objects.update_or_create(
        key="runtime.input_limits",
        defaults={"value": {"max_message_length_chars": 321, "max_payload_bytes": 654}, "is_active": True},
    )
    RuntimeConfig.objects.update_or_create(
        key="quota.guest_policy",
        defaults={"value": {"token_limit": 111, "window_seconds": 222}, "is_active": True},
    )
    RuntimeConfig.objects.update_or_create(
        key="quota.user_policy",
        defaults={"value": {"token_limit": 333, "window_seconds": 444}, "is_active": True},
    )
    RuntimeConfig.objects.update_or_create(
        key="quota.pending_input_limits",
        defaults={"value": {"max_appends": 5, "max_chars": 42}, "is_active": True},
    )
    RuntimeConfig.objects.update_or_create(
        key="runtime.step_trace",
        defaults={"value": {"level": "meta"}, "is_active": True},
    )

    assert service.input_limits() == RuntimeInputLimits(max_message_length_chars=321, max_payload_bytes=654)
    assert service.guest_quota_policy() == QuotaPolicy(token_limit=111, window_seconds=222)
    assert service.user_quota_policy() == QuotaPolicy(token_limit=333, window_seconds=444)
    assert service.pending_input_limits() == PendingInputLimits(max_appends=5, max_chars=42)
    assert service.step_trace_config() == StepTraceConfig(level="meta")


def test_quota_service_creates_and_rolls_current_window() -> None:
    """Quota service creates a current window and rolls it forward when expired."""

    RuntimeConfig.objects.update_or_create(
        key="quota.guest_policy",
        defaults={"value": {"token_limit": 123, "window_seconds": 86400}, "is_active": True},
    )
    guest = GuestIdentity.objects.create()
    service = QuotaService()

    current = service.current_for_identity(guest_identity=guest)

    assert current.token_limit == 123
    assert current.window_ends_at == current.window_started_at + timedelta(seconds=86400)

    current.window_started_at = timezone.now() - timedelta(days=2)
    current.window_ends_at = current.window_started_at + timedelta(seconds=86400)
    current.save(update_fields=["window_started_at", "window_ends_at", "updated_at"])

    rolled = service.current_for_identity(guest_identity=guest)

    assert rolled.id != current.id
    assert rolled.token_limit == 123
    assert rolled.window_started_at >= current.window_started_at


def test_request_gate_uses_configured_input_limits() -> None:
    """Request gate reads max message length and payload size from runtime config."""

    RuntimeConfig.objects.update_or_create(
        key="runtime.input_limits",
        defaults={"value": {"max_message_length_chars": 3, "max_payload_bytes": 200}, "is_active": True},
    )
    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    pipeline = RequestGatePipeline()

    result = pipeline._input_guard(
        request=type("Request", (), {"body": b'{"message":"abcd"}'})(),
        payload=type("Payload", (), {"message": "abcd"})(),
        data={"message": "abcd"},
    )

    assert result.passed is False
    assert result.error_code == "message_too_long"


def test_request_gate_payload_size_uses_raw_body_bytes() -> None:
    """Payload hard-limit check must use raw request body size."""

    RuntimeConfig.objects.update_or_create(
        key="runtime.input_limits",
        defaults={"value": {"max_message_length_chars": 1000, "max_payload_bytes": 10}, "is_active": True},
    )
    pipeline = RequestGatePipeline()

    result = pipeline._input_guard(
        request=type("Request", (), {"body": b'{"message":"0123456789ABC"}'})(),
        payload=type("Payload", (), {"message": "ok"})(),
        data={"message": "ok"},
    )

    assert result.passed is False
    assert result.error_code == "payload_too_large"


def test_pending_input_append_respects_config_bounds() -> None:
    """Blocked input storage obeys the admin-configured append and size caps."""

    RuntimeConfig.objects.update_or_create(
        key="quota.pending_input_limits",
        defaults={"value": {"max_appends": 1, "max_chars": 20}, "is_active": True},
    )
    RuntimeConfig.objects.update_or_create(
        key="runtime.input_limits",
        defaults={"value": {"max_message_length_chars": 8, "max_payload_bytes": 65536}, "is_active": True},
    )
    guest = GuestIdentity.objects.create()
    quota_window = UsageQuotaWindow.objects.create(guest_identity=guest, is_exhausted=True)

    updated = QuotaService().append_pending_input(quota_window, "first blocked message")
    updated.refresh_from_db()
    assert updated.pending_input_append_count == 1
    assert updated.pending_input_text == "first blocked message"[:8]

    second = QuotaService().append_pending_input(updated, "second blocked message")
    second.refresh_from_db()
    assert second.pending_input_append_count == 1
    assert "second" not in second.pending_input_text


def test_chat_turn_step12_updates_quota_window() -> None:
    """A real runtime turn finalizes usage and updates the current quota window."""

    RuntimeConfig.objects.update_or_create(
        key="quota.guest_policy",
        defaults={"value": {"token_limit": 1, "window_seconds": 86400}, "is_active": True},
    )
    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)

    response = api_client_with_guest(guest).post(
        "/api/chat/message/",
        {"message": "hello quota"},
        format="json",
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"
    events = parse_sse_stream(b"".join(response.streaming_content))

    turn = ChatTurn.objects.filter(guest_identity=guest).latest("created_at")
    quota_window = UsageQuotaWindow.current_for_identity(guest_identity=guest)
    done = next(e for e in events if e["type"] == "done")
    assert done["data"]["quota_exhausted_after_turn"] is True
    assert turn.usage_accounting_status == "finalized"
    assert turn.step12_finalization_status == "finalized"
    assert turn.quota_window_before["token_limit"] == 1
    assert turn.quota_window_after["is_exhausted"] is True
    assert turn.quota_exhausted_after_turn is True
    assert quota_window.is_exhausted is True
    assert quota_window.used_tokens >= 1
