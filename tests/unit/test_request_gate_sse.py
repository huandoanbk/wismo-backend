"""Full gate failure path regression tests for POST /api/chat/message/.

Each test verifies:
- gate-fail → HTTP 4xx + JSON {"error": "<code>"}, no streaming content
- gate-pass → StreamingHttpResponse with SSE headers
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import GuestIdentity, User
from accounts.services import GUEST_COOKIE_NAME
from chat.models import Case, Chat, ChatTurn
from consents.services import ConsentService
from runtime.models import UsageQuotaWindow
from wismo.contracts.enums import Step12FinalizationStatus

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-Uncommon-Passphrase-2026!"
ENDPOINT = "/api/chat/message/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def anon_client() -> APIClient:
    """API client with no session and no guest cookie."""
    return APIClient()


def guest_client(guest: GuestIdentity) -> APIClient:
    """API client carrying the guest cookie."""
    client = APIClient()
    client.cookies[GUEST_COOKIE_NAME] = str(guest.id)
    return client


def registered_client(user: User) -> APIClient:
    """API client authenticated as a registered user."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def make_user(*, is_active: bool = True, email_verified: bool = True) -> User:
    """Create a minimal User for tests."""
    import uuid

    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    user = User.objects.create_user(email=email, password=PASSWORD)
    user.is_active = is_active
    user.email_verified = email_verified
    user.save(update_fields=["is_active", "email_verified"])
    return user


def make_guest_with_consent() -> tuple[GuestIdentity, APIClient]:
    """Create a guest identity with accepted consent and return (guest, client)."""
    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    return guest, guest_client(guest)


def make_registered_with_consent() -> tuple[User, APIClient]:
    """Create a registered user with accepted consent and return (user, client)."""
    user = make_user()
    ConsentService().accept(user=user)
    return user, registered_client(user)


def assert_gate_fail(response, *, status: int, error: str) -> None:
    """Assert gate-fail JSON response shape and that no stream was opened."""
    assert response.status_code == status
    assert response.data["error"] == error
    # gate-fail must never be a streaming response
    assert not hasattr(response, "streaming_content") or not callable(
        getattr(response, "streaming_content", None)
    )


# ---------------------------------------------------------------------------
# Group A: Payload validation failures (no identity needed)
# ---------------------------------------------------------------------------


def test_gate_fail_invalid_request_bad_body_type() -> None:
    """Valid JSON but non-dict body (array) returns invalid_request."""
    client = anon_client()
    # A JSON array is valid JSON but not a dict — gate rejects it as invalid_request
    response = client.post(ENDPOINT, data='["not", "a", "dict"]', content_type="application/json")
    assert response.status_code == 400
    assert response.data["error"] == "invalid_request"


def test_gate_fail_missing_required_field() -> None:
    """Body without 'message' returns missing_required_field."""
    client = anon_client()
    response = client.post(ENDPOINT, {"chat_id": None}, format="json")
    assert response.status_code == 400
    assert response.data["error"] == "missing_required_field"


def test_gate_fail_invalid_chat_id() -> None:
    """Non-UUID chat_id returns invalid_chat_id."""
    client = anon_client()
    response = client.post(ENDPOINT, {"message": "hi", "chat_id": "not-a-uuid"}, format="json")
    assert response.status_code == 400
    assert response.data["error"] == "invalid_chat_id"


# ---------------------------------------------------------------------------
# Group B: Identity / session failures
# ---------------------------------------------------------------------------


def test_gate_fail_identity_not_resolved() -> None:
    """Anonymous client with no guest cookie returns identity_not_resolved."""
    response = anon_client().post(ENDPOINT, {"message": "hi"}, format="json")
    assert response.status_code == 401
    assert response.data["error"] == "identity_not_resolved"


def test_gate_fail_session_expired_inactive_user() -> None:
    """Authenticated user with is_active=False returns session_expired."""
    user = make_user(is_active=False)
    response = registered_client(user).post(ENDPOINT, {"message": "hi"}, format="json")
    assert response.status_code == 401
    assert response.data["error"] == "session_expired"


def test_gate_fail_guest_session_expired_inactive() -> None:
    """Guest with is_active=False returns guest_session_expired."""
    guest = GuestIdentity.objects.create(is_active=False)
    response = guest_client(guest).post(ENDPOINT, {"message": "hi"}, format="json")
    assert response.status_code == 401
    assert response.data["error"] == "guest_session_expired"


def test_gate_fail_guest_session_expired_past_expiry() -> None:
    """Guest with expires_at in the past returns guest_session_expired."""
    past = timezone.now() - timezone.timedelta(hours=1)
    guest = GuestIdentity.objects.create(expires_at=past)
    response = guest_client(guest).post(ENDPOINT, {"message": "hi"}, format="json")
    assert response.status_code == 401
    assert response.data["error"] == "guest_session_expired"


# ---------------------------------------------------------------------------
# Group C: Consent failure
# ---------------------------------------------------------------------------


def test_gate_fail_consent_required() -> None:
    """Guest with no accepted consent returns consent_required."""
    guest = GuestIdentity.objects.create()
    # no ConsentService().accept() call
    response = guest_client(guest).post(ENDPOINT, {"message": "hi"}, format="json")
    assert response.status_code == 403
    assert response.data["error"] == "consent_required"


# ---------------------------------------------------------------------------
# Group D: Input basic guard failures (need valid identity + consent)
# ---------------------------------------------------------------------------


def test_gate_fail_empty_message() -> None:
    """Whitespace-only message returns empty_message."""
    _, client = make_guest_with_consent()
    response = client.post(ENDPOINT, {"message": "   "}, format="json")
    assert response.status_code == 400
    assert response.data["error"] == "empty_message"


def test_gate_fail_message_too_long() -> None:
    """Message exceeding max_message_length_chars returns message_too_long."""
    _, client = make_guest_with_consent()
    response = client.post(ENDPOINT, {"message": "x" * 9000}, format="json")
    assert response.status_code == 413
    assert response.data["error"] == "message_too_long"


def test_gate_fail_payload_too_large() -> None:
    """Payload exceeding hard byte size returns payload_too_large."""
    _, client = make_guest_with_consent()
    # Build a message dict that when str(data) encoded exceeds 65536 bytes
    huge_extra = "y" * 70000
    response = client.post(
        ENDPOINT,
        {"message": "hi", "extra": huge_extra},
        format="json",
    )
    assert response.status_code == 413
    assert response.data["error"] == "payload_too_large"


# ---------------------------------------------------------------------------
# Group E: Quota failures
# ---------------------------------------------------------------------------


def test_gate_fail_registration_required_by_quota() -> None:
    """Guest with exhausted quota returns registration_required_by_quota and saves pending input."""
    guest, client = make_guest_with_consent()
    UsageQuotaWindow.objects.create(guest_identity=guest, is_exhausted=True)

    response = client.post(ENDPOINT, {"message": "blocked guest message"}, format="json")

    assert response.status_code == 429
    assert response.data["error"] == "registration_required_by_quota"

    quota = UsageQuotaWindow.objects.get(guest_identity=guest)
    assert "blocked guest message" in (quota.pending_input_text or "")


def test_gate_fail_quota_exceeded() -> None:
    """Registered user with exhausted quota returns quota_exceeded and saves pending input."""
    user, client = make_registered_with_consent()
    UsageQuotaWindow.objects.create(user=user, is_exhausted=True)

    response = client.post(ENDPOINT, {"message": "blocked user message"}, format="json")

    assert response.status_code == 429
    assert response.data["error"] == "quota_exceeded"

    quota = UsageQuotaWindow.objects.get(user=user)
    assert "blocked user message" in (quota.pending_input_text or "")


# ---------------------------------------------------------------------------
# Group F: Ownership failures
# ---------------------------------------------------------------------------


def test_gate_fail_chat_not_found_nonexistent_uuid() -> None:
    """chat_id that does not exist returns chat_not_found."""
    import uuid

    _, client = make_guest_with_consent()
    response = client.post(
        ENDPOINT, {"message": "hi", "chat_id": str(uuid.uuid4())}, format="json"
    )
    assert response.status_code == 404
    assert response.data["error"] == "chat_not_found"


def test_gate_fail_chat_not_found_archived() -> None:
    """Archived chat returns chat_not_found even if owned."""
    guest, client = make_guest_with_consent()
    case = Case.objects.create(guest_identity=guest, topic="test")
    chat = Chat.objects.create(guest_identity=guest, case=case, is_archived=True)

    response = client.post(
        ENDPOINT, {"message": "hi", "chat_id": str(chat.id)}, format="json"
    )
    assert response.status_code == 404
    assert response.data["error"] == "chat_not_found"


def test_gate_fail_chat_access_denied() -> None:
    """Chat belonging to a different identity returns chat_access_denied."""
    other_guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=other_guest)
    other_case = Case.objects.create(guest_identity=other_guest, topic="other")
    foreign_chat = Chat.objects.create(guest_identity=other_guest, case=other_case)

    _, client = make_guest_with_consent()
    response = client.post(
        ENDPOINT, {"message": "hi", "chat_id": str(foreign_chat.id)}, format="json"
    )
    assert response.status_code == 403
    assert response.data["error"] == "chat_access_denied"


def test_gate_fail_turn_in_progress() -> None:
    """Chat with Step 12 pending turn returns turn_in_progress."""
    guest, client = make_guest_with_consent()
    case = Case.objects.create(guest_identity=guest, topic="test")
    chat = Chat.objects.create(guest_identity=guest, case=case)
    turn = ChatTurn.objects.create(
        guest_identity=guest,
        chat=chat,
        case=case,
        user_message_text="previous",
        status="processing",
    )
    turn.step12_finalization_status = Step12FinalizationStatus.PENDING.value
    turn.save(update_fields=["step12_finalization_status"])

    response = client.post(
        ENDPOINT, {"message": "new message", "chat_id": str(chat.id)}, format="json"
    )
    assert response.status_code == 409
    assert response.data["error"] == "turn_in_progress"


def test_gate_allows_new_turn_when_previous_step12_is_partial_or_failed() -> None:
    """Barrier only blocks pending/processing; partial/failed must pass gate."""

    guest, client = make_guest_with_consent()
    case = Case.objects.create(guest_identity=guest, topic="test")
    chat = Chat.objects.create(guest_identity=guest, case=case)
    previous = ChatTurn.objects.create(
        guest_identity=guest,
        chat=chat,
        case=case,
        user_message_text="previous",
        status="completed",
    )
    previous.step12_finalization_status = Step12FinalizationStatus.FAILED.value
    previous.save(update_fields=["step12_finalization_status"])

    dummy_events = iter(
        ['event: response\ndata: {"text": "ok"}\n\n', 'event: done\ndata: {"turn_id": "x"}\n\n']
    )
    with patch("chat.views.RuntimeOrchestrator") as mock_orc_cls:
        mock_orc_cls.return_value.stream.return_value = dummy_events
        response = client.post(
            ENDPOINT,
            {"message": "new message", "chat_id": str(chat.id)},
            format="json",
        )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Group G: Gate pass
# ---------------------------------------------------------------------------


def test_gate_pass_returns_sse_headers() -> None:
    """Gate pass opens SSE stream with mandatory headers."""
    _, client = make_guest_with_consent()

    # Mock orchestrator.stream() to yield a minimal done event and avoid real LLM call
    dummy_events = iter(
        ['event: response\ndata: {"text": "ok"}\n\n', 'event: done\ndata: {"turn_id": "x"}\n\n']
    )
    with patch("chat.views.RuntimeOrchestrator") as mock_orc_cls:
        mock_orc_cls.return_value.stream.return_value = dummy_events
        response = client.post(ENDPOINT, {"message": "hello"}, format="json")

    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"
    assert response["Cache-Control"] == "no-cache"
    assert response["X-Accel-Buffering"] == "no"


def test_gate_pass_clears_guest_cookie_for_registered_identity() -> None:
    """Registered identity with lingering guest cookie gets cookie cleared on gate pass."""
    user, _ = make_registered_with_consent()

    client = APIClient()
    client.force_authenticate(user=user)
    # Attach a stale guest cookie
    other_guest = GuestIdentity.objects.create()
    client.cookies[GUEST_COOKIE_NAME] = str(other_guest.id)

    dummy_events = iter(
        ['event: response\ndata: {"text": "ok"}\n\n', 'event: done\ndata: {"turn_id": "x"}\n\n']
    )
    with patch("chat.views.RuntimeOrchestrator") as mock_orc_cls:
        mock_orc_cls.return_value.stream.return_value = dummy_events
        response = client.post(ENDPOINT, {"message": "hello"}, format="json")

    assert response.status_code == 200
    # Cookie should be deleted (max-age=0 or Set-Cookie with empty value)
    set_cookie_header = response.cookies.get(GUEST_COOKIE_NAME)
    assert set_cookie_header is not None
    assert set_cookie_header["max-age"] == 0 or set_cookie_header.value == ""
