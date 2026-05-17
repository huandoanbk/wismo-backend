"""Regression tests for chat bootstrap list/create/detail APIs."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import GuestIdentity, User
from accounts.services import GUEST_COOKIE_NAME
from chat.models import Chat, ChatTurn
from chat.services import CHAT_DISPLAY_NAME_FALLBACK
from wismo.contracts.enums import ResponseMethod, TurnStatus

pytestmark = pytest.mark.django_db


def api_client_with_guest(guest: GuestIdentity) -> APIClient:
    """Return an API client carrying the guest cookie."""

    client = APIClient()
    client.cookies[GUEST_COOKIE_NAME] = str(guest.id)
    return client


def create_verified_user(email: str) -> User:
    """Create a verified registered user for bootstrap tests."""

    return User.objects.create_user(
        email=email,
        password="Str0ng-Uncommon-Passphrase-2026!",
        email_verified=True,
    )


def create_chat(
    *,
    guest_identity: GuestIdentity | None = None,
    user: User | None = None,
    chat_display_name: str = CHAT_DISPLAY_NAME_FALLBACK,
    opening_input_text: str = "",
    last_activity_at: datetime | None = None,
) -> Chat:
    """Create a chat row with the requested owner and canonical metadata."""

    if last_activity_at is None:
        last_activity_at = timezone.now()
    return Chat.objects.create(
        user=user,
        guest_identity=guest_identity,
        chat_display_name=chat_display_name,
        opening_input_text=opening_input_text,
        last_activity_at=last_activity_at,
    )


def create_turn(
    *,
    chat: Chat,
    guest_identity: GuestIdentity | None = None,
    user: User | None = None,
    user_message_text: str,
    assistant_response_text: str,
    created_at: datetime,
    finalized_at: datetime,
) -> ChatTurn:
    """Create a completed turn with explicit timestamps for ordering tests."""

    turn = ChatTurn.objects.create(
        chat=chat,
        guest_identity=guest_identity,
        user=user,
        user_message_text=user_message_text,
        assistant_response_text=assistant_response_text,
        response_method=ResponseMethod.ASK.value,
        status=TurnStatus.COMPLETED.value,
        finalized_at=finalized_at,
    )
    ChatTurn.objects.filter(id=turn.id).update(
        created_at=created_at,
        finalized_at=finalized_at,
    )
    return ChatTurn.objects.get(id=turn.id)


def test_chat_bootstrap_create_returns_fallback_display_name_and_opening_input_text() -> None:
    """Create returns a chat shell with canonical fallback metadata."""

    guest = GuestIdentity.objects.create()
    client = api_client_with_guest(guest)

    response = client.post(
        "/api/chat/",
        {"opening_input_text": "hello there"},
        format="json",
    )

    assert response.status_code == 201
    chat_payload = response.data["chat"]
    assert chat_payload["chat_display_name"] == CHAT_DISPLAY_NAME_FALLBACK
    assert chat_payload["case_id"] is None
    assert chat_payload["opening_input_text"] == "hello there"

    chat = Chat.objects.get(id=chat_payload["chat_id"])
    assert chat.guest_identity_id == guest.id
    assert chat.chat_display_name == CHAT_DISPLAY_NAME_FALLBACK
    assert chat.opening_input_text == "hello there"
    assert chat.case_id is None


def test_chat_bootstrap_list_orders_owned_chats_and_is_summary_only() -> None:
    """List returns only owned chat summaries ordered by recency."""

    user = create_verified_user("list-user@example.com")
    client = APIClient()
    client.force_login(user)

    older = create_chat(
        user=user,
        chat_display_name="Older chat",
        last_activity_at=timezone.now() - timedelta(minutes=10),
    )
    newer = create_chat(
        user=user,
        chat_display_name="Newer chat",
        last_activity_at=timezone.now() - timedelta(minutes=1),
    )
    create_chat(
        guest_identity=GuestIdentity.objects.create(),
        chat_display_name="Foreign chat",
        last_activity_at=timezone.now(),
    )

    response = client.get("/api/chat/")

    assert response.status_code == 200
    chat_ids = [item["chat_id"] for item in response.data["chats"]]
    assert chat_ids == [str(newer.id), str(older.id)]
    assert all("turns" not in item for item in response.data["chats"])
    assert response.data["chats"][0]["case_id"] is None
    assert response.data["chats"][0]["chat_display_name"] == "Newer chat"


def test_chat_bootstrap_detail_returns_turn_history_in_chronological_order() -> None:
    """Detail returns summary plus ordered turn history for the current identity."""

    guest = GuestIdentity.objects.create()
    client = api_client_with_guest(guest)
    chat = create_chat(
        guest_identity=guest,
        opening_input_text="seed message",
        last_activity_at=timezone.now(),
    )
    first_turn = create_turn(
        chat=chat,
        guest_identity=guest,
        user_message_text="first",
        assistant_response_text="reply-1",
        created_at=timezone.now() - timedelta(minutes=2),
        finalized_at=timezone.now() - timedelta(minutes=2, seconds=30),
    )
    second_turn = create_turn(
        chat=chat,
        guest_identity=guest,
        user_message_text="second",
        assistant_response_text="reply-2",
        created_at=timezone.now() - timedelta(minutes=1),
        finalized_at=timezone.now() - timedelta(minutes=1, seconds=30),
    )

    response = client.get(f"/api/chat/{chat.id}/")

    assert response.status_code == 200
    assert response.data["chat"]["chat_id"] == str(chat.id)
    assert response.data["chat"]["chat_display_name"] == CHAT_DISPLAY_NAME_FALLBACK
    assert response.data["chat"]["opening_input_text"] == "seed message"
    assert [turn["turn_id"] for turn in response.data["turns"]] == [str(first_turn.id), str(second_turn.id)]
    assert response.data["turns"][0]["user_message_text"] == "first"
    assert response.data["turns"][1]["assistant_response_text"] == "reply-2"
    assert response.data["turns"][0]["case_id"] is None


def test_chat_bootstrap_detail_denies_foreign_chat_and_missing_chat() -> None:
    """Detail rejects foreign ownership and missing chats with canonical errors."""

    owner_guest = GuestIdentity.objects.create()
    other_guest = GuestIdentity.objects.create()
    chat = create_chat(guest_identity=owner_guest)
    client = api_client_with_guest(other_guest)

    denied = client.get(f"/api/chat/{chat.id}/")
    missing = client.get(f"/api/chat/{uuid.uuid4()}/")

    assert denied.status_code == 403
    assert denied.data == {"error": "chat_access_denied"}
    assert missing.status_code == 404
    assert missing.data == {"error": "chat_not_found"}


def test_chat_bootstrap_requires_resolved_identity() -> None:
    """Bootstrap endpoints reject requests without a resolved identity."""

    response = APIClient().get("/api/chat/")

    assert response.status_code == 401
    assert response.data == {"error": "identity_not_resolved"}


def test_chat_bootstrap_reports_expired_guest_and_invalid_chat_id() -> None:
    """Bootstrap endpoints surface guest expiry and malformed chat_id canonically."""

    valid_guest = GuestIdentity.objects.create()
    valid_client = api_client_with_guest(valid_guest)
    invalid = valid_client.get("/api/chat/not-a-uuid/")

    expired_guest = GuestIdentity.objects.create(
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    client = api_client_with_guest(expired_guest)

    expired = client.get("/api/chat/")

    assert invalid.status_code == 400
    assert invalid.data == {"error": "invalid_request"}
    assert expired.status_code == 401
    assert expired.data == {"error": "guest_session_expired"}


def test_chat_bootstrap_reports_session_expired_for_inactive_registered_user() -> None:
    """Bootstrap endpoints reject unverified registered sessions with session_expired."""

    user = create_verified_user("inactive-user@example.com")
    user.email_verified = False
    user.save(update_fields=["email_verified"])

    client = APIClient()
    client.force_login(user)
    response = client.get("/api/chat/")

    assert response.status_code == 401
    assert response.data == {"error": "session_expired"}


def test_chat_delete_archives_owned_chat() -> None:
    """DELETE sets is_archived=True and returns 200 with archived=True."""

    guest = GuestIdentity.objects.create()
    client = api_client_with_guest(guest)
    chat = create_chat(guest_identity=guest)

    response = client.delete(f"/api/chat/{chat.id}/")

    assert response.status_code == 200
    assert response.data == {"archived": True}
    chat.refresh_from_db()
    assert chat.is_archived is True


def test_chat_delete_rejects_foreign_ownership() -> None:
    """DELETE on a chat owned by another identity returns 403."""

    owner = GuestIdentity.objects.create()
    other = GuestIdentity.objects.create()
    chat = create_chat(guest_identity=owner)
    client = api_client_with_guest(other)

    response = client.delete(f"/api/chat/{chat.id}/")

    assert response.status_code == 403
    assert response.data == {"error": "chat_access_denied"}


def test_chat_delete_rejects_missing_chat() -> None:
    """DELETE on a non-existent chat_id returns 404."""

    guest = GuestIdentity.objects.create()
    client = api_client_with_guest(guest)

    response = client.delete(f"/api/chat/{uuid.uuid4()}/")

    assert response.status_code == 404
    assert response.data == {"error": "chat_not_found"}


def test_chat_delete_rejects_turn_in_progress() -> None:
    """DELETE returns 409 when the chat has a processing turn."""

    guest = GuestIdentity.objects.create()
    client = api_client_with_guest(guest)
    chat = create_chat(guest_identity=guest)
    ChatTurn.objects.create(
        chat=chat,
        guest_identity=guest,
        user_message_text="active",
        assistant_response_text="",
        response_method=ResponseMethod.ASK.value,
        status="processing",
    )

    response = client.delete(f"/api/chat/{chat.id}/")

    assert response.status_code == 409
    assert response.data == {"error": "turn_in_progress"}
    chat.refresh_from_db()
    assert chat.is_archived is False


def test_chat_delete_requires_resolved_identity() -> None:
    """DELETE without identity returns 401."""

    guest = GuestIdentity.objects.create()
    chat = create_chat(guest_identity=guest)

    response = APIClient().delete(f"/api/chat/{chat.id}/")

    assert response.status_code == 401
    assert response.data == {"error": "identity_not_resolved"}
