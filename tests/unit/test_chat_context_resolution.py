"""Regression tests for Step 3 chat-context resolution behavior."""

from __future__ import annotations

import json

import pytest
from rest_framework.test import APIClient

from accounts.models import GuestIdentity
from accounts.services import GUEST_COOKIE_NAME
from chat.models import Chat, ChatTurn
from consents.services import ConsentService

pytestmark = pytest.mark.django_db


def _client_with_guest(guest: GuestIdentity) -> APIClient:
    """Return API client carrying canonical guest cookie."""

    client = APIClient()
    client.cookies[GUEST_COOKIE_NAME] = str(guest.id)
    return client


def _parse_sse_stream(content: bytes) -> list[dict]:
    """Parse SSE response bytes into {type, data} entries."""

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
        if event_type:
            events.append({"type": event_type, "data": data})
    return events


def test_chat_message_without_chat_id_creates_chat_with_opening_input_and_turn() -> None:
    """No chat_id path creates chat shell and one canonical turn."""

    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    client = _client_with_guest(guest)

    response = client.post("/api/chat/message/", {"message": "seed opening"}, format="json")

    assert response.status_code == 200
    events = _parse_sse_stream(b"".join(response.streaming_content))
    done = next(event for event in events if event["type"] == "done")

    chat = Chat.objects.get(id=done["data"]["chat_id"])
    turn = ChatTurn.objects.get(id=done["data"]["turn_id"])

    assert chat.guest_identity_id == guest.id
    assert chat.opening_input_text == "seed opening"
    assert turn.chat_id == chat.id
    assert turn.user_message_text == "seed opening"
    assert turn.case_id == chat.case_id
    assert ChatTurn.objects.filter(chat=chat).count() == 1
    assert done["data"]["chat_display_name"] == chat.chat_display_name


def test_chat_message_with_chat_id_loads_existing_chat_and_keeps_opening_input() -> None:
    """chat_id path reuses existing chat and does not overwrite opening input text."""

    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    existing_chat = Chat.objects.create(
        guest_identity=guest,
        chat_display_name="Existing",
        opening_input_text="original opening",
    )
    client = _client_with_guest(guest)

    response = client.post(
        "/api/chat/message/",
        {"message": "follow up", "chat_id": str(existing_chat.id)},
        format="json",
    )

    assert response.status_code == 200
    events = _parse_sse_stream(b"".join(response.streaming_content))
    done = next(event for event in events if event["type"] == "done")

    existing_chat.refresh_from_db()
    turn = ChatTurn.objects.get(id=done["data"]["turn_id"])

    assert done["data"]["chat_id"] == str(existing_chat.id)
    assert done["data"]["chat_display_name"] == existing_chat.chat_display_name
    assert existing_chat.opening_input_text == "original opening"
    assert turn.chat_id == existing_chat.id
    assert turn.user_message_text == "follow up"
    assert turn.case_id == existing_chat.case_id
    assert Chat.objects.filter(guest_identity=guest).count() == 1
    assert ChatTurn.objects.filter(chat=existing_chat).count() == 1
