"""SSE transport layer regression tests for POST /api/chat/message/."""

from __future__ import annotations

import json

import pytest
from rest_framework.test import APIClient

from accounts.models import GuestIdentity, User
from accounts.services import GUEST_COOKIE_NAME
from consents.services import ConsentService

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-Uncommon-Passphrase-2026!"


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


def test_chat_message_success_returns_sse_stream() -> None:
    """Gate pass opens SSE stream with response and done events."""

    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    client = api_client_with_guest(guest)

    response = client.post(
        "/api/chat/message/",
        {"message": "hello world"},
        format="json",
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"
    assert response["Cache-Control"] == "no-cache"
    assert response["X-Accel-Buffering"] == "no"

    events = parse_sse_stream(b"".join(response.streaming_content))
    event_types = [e["type"] for e in events]
    assert "response" in event_types
    assert "done" in event_types

    response_event = next(e for e in events if e["type"] == "response")
    done_event = next(e for e in events if e["type"] == "done")

    assert isinstance(response_event["data"]["text"], str)
    assert len(response_event["data"]["text"]) > 0

    assert done_event["data"]["chat_id"]
    assert done_event["data"]["chat_display_name"]
    assert done_event["data"]["turn_id"]
    assert done_event["data"]["response_method"]
    assert done_event["data"]["status"] == "completed"
    assert isinstance(done_event["data"]["quota_exhausted_after_turn"], bool)
    assert "step12_finalization_status" not in done_event["data"]


def test_chat_message_gate_fail_returns_json_not_sse() -> None:
    """All gate error paths return JSON, not SSE stream."""

    anon = APIClient()

    missing_identity = anon.post(
        "/api/chat/message/",
        {"message": "hello"},
        format="json",
    )
    assert missing_identity.status_code == 401
    assert missing_identity.data["error"] == "identity_not_resolved"
    assert "text/event-stream" not in missing_identity.get("Content-Type", "")

    guest = GuestIdentity.objects.create()
    client = api_client_with_guest(guest)

    no_consent = client.post(
        "/api/chat/message/",
        {"message": "hello"},
        format="json",
    )
    assert no_consent.status_code == 403
    assert no_consent.data["error"] == "consent_required"
    assert "text/event-stream" not in no_consent.get("Content-Type", "")

    missing_field = anon.post(
        "/api/chat/message/",
        {},
        format="json",
    )
    assert missing_field.status_code == 400
    assert missing_field.data["error"] == "missing_required_field"
    assert "text/event-stream" not in missing_field.get("Content-Type", "")


def test_chat_message_sse_done_event_order() -> None:
    """SSE stream always has response event before done event."""

    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    client = api_client_with_guest(guest)

    response = client.post(
        "/api/chat/message/",
        {"message": "ordering test"},
        format="json",
    )

    events = parse_sse_stream(b"".join(response.streaming_content))
    types = [e["type"] for e in events]

    assert "response" in types
    assert "done" in types
    assert types.index("response") < types.index("done")


def test_chat_message_sse_clear_guest_cookie_on_registered_identity() -> None:
    """SSE response clears stale guest cookie when registered identity is canonical."""

    user = User.objects.create_user(
        email="sse-cookie@example.com",
        password=PASSWORD,
        is_active=True,
        email_verified=True,
    )
    ConsentService().accept(user=user)
    guest = GuestIdentity.objects.create()

    client = api_client_with_guest(guest)
    client.force_login(user)

    response = client.post(
        "/api/chat/message/",
        {"message": "hello"},
        format="json",
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"
    assert response.cookies[GUEST_COOKIE_NAME]["max-age"] == 0
