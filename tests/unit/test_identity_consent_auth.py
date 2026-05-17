"""Identity, consent, OTP auth, attach, and request gate regression tests."""

from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import GuestIdentity, User
from accounts.services import GUEST_COOKIE_NAME
from chat.models import Case, Chat, ChatTurn
from consents.services import ConsentService
from runtime.models import UsageQuotaWindow


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

PASSWORD = "Str0ng-Uncommon-Passphrase-2026!"


pytestmark = pytest.mark.django_db


def extract_otp() -> str:
    """Extract the latest OTP from Django locmem email outbox."""

    match = re.search(r"\b(\d{6})\b", mail.outbox[-1].body)
    assert match is not None
    return match.group(1)


def api_client_with_guest(guest: GuestIdentity) -> APIClient:
    """Return an API client carrying the guest cookie."""

    client = APIClient()
    client.cookies[GUEST_COOKIE_NAME] = str(guest.id)
    return client


def create_verified_user(email: str = "user@example.com", password: str = PASSWORD) -> User:
    """Create a verified registered user for auth/session tests."""

    return User.objects.create_user(email=email, password=password, email_verified=True)


@pytest.fixture(autouse=True)
def locmem_email_backend(settings) -> None:
    """Use in-memory email delivery for OTP tests."""

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


def test_guest_init_and_session_status_guest() -> None:
    """Guest init sets the canonical guest cookie and status."""

    client = APIClient()
    response = client.post("/api/accounts/guest/init/", {}, format="json")

    assert response.status_code == 201
    assert response.data["session_state"] == "guest"
    assert response.data["consent_state"] == "required"
    assert GUEST_COOKIE_NAME in response.cookies

    client.cookies[GUEST_COOKIE_NAME] = response.data["guest_token"]
    status = client.get("/api/accounts/session/")

    assert status.status_code == 200
    assert status.data["session_state"] == "guest"
    assert status.data["identity_type"] == "guest"
    assert status.data["consent_state"] == "required"


def test_legacy_chat_guest_init_route_is_removed() -> None:
    """Guest init is exposed only through the accounts route."""

    response = APIClient().post("/api/chat/guest/init/", {}, format="json")

    assert response.status_code == 404


def test_session_status_unauthenticated_and_expired_guest() -> None:
    """Expired guest session is treated as unauthenticated — same as no session."""

    assert APIClient().get("/api/accounts/session/").data == {
        "session_state": "unauthenticated",
        "identity_type": "none",
        "consent_state": "unknown",
    }

    guest = GuestIdentity.objects.create(expires_at=timezone.now() - timedelta(minutes=1))
    client = api_client_with_guest(guest)
    response = client.get("/api/accounts/session/")

    assert response.status_code == 200
    assert response.data["session_state"] == "unauthenticated"
    assert response.data["identity_type"] == "none"


def test_session_status_session_expired_for_inactive_registered_user() -> None:
    """Session status returns session_expired for authenticated but inactive/unverified user."""

    user = User.objects.create_user(email="inactive@example.com", password="Pass1234!")
    user.is_active = False
    user.email_verified = True
    user.save(update_fields=["is_active", "email_verified"])

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/accounts/session/")

    assert response.status_code == 200
    assert response.data["session_state"] == "session_expired"
    assert response.data["identity_type"] == "user"
    assert response.data["consent_state"] == "unknown"
    assert response.data["user"]["email"] == "inactive@example.com"


def test_session_status_session_expired_for_unverified_registered_user() -> None:
    """Session status returns session_expired for authenticated but email-unverified user."""

    user = User.objects.create_user(email="unverified@example.com", password="Pass1234!")
    user.is_active = True
    user.email_verified = False
    user.save(update_fields=["is_active", "email_verified"])

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/accounts/session/")

    assert response.status_code == 200
    assert response.data["session_state"] == "session_expired"
    assert response.data["identity_type"] == "user"
    assert response.data["consent_state"] == "unknown"


def test_consent_accept_and_status_for_guest_and_registered_user() -> None:
    """Consent APIs return canonical state for guest and user identities."""

    guest = GuestIdentity.objects.create()
    guest_client = api_client_with_guest(guest)

    accept_guest = guest_client.post("/api/consents/accept/", {}, format="json")
    status_guest = guest_client.get("/api/consents/status/")

    assert accept_guest.status_code == 201
    assert accept_guest.data["identity_type"] == "guest"
    assert accept_guest.data["consent_state"] == "accepted"
    assert status_guest.data == {"identity_type": "guest", "consent_state": "accepted"}

    user = create_verified_user("consent-user@example.com")
    user_client = APIClient()
    user_client.force_login(user)

    accept_user = user_client.post("/api/consents/accept/", {}, format="json")
    status_user = user_client.get("/api/consents/status/")

    assert accept_user.status_code == 201
    assert accept_user.data["identity_type"] == "user"
    assert status_user.data == {"identity_type": "user", "consent_state": "accepted"}


def test_consent_withdraw_for_guest_and_registered_user() -> None:
    """Consent withdrawal flips the canonical state back to required."""

    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    guest_client = api_client_with_guest(guest)

    withdraw_guest = guest_client.post("/api/consents/withdraw/", {}, format="json")
    status_guest = guest_client.get("/api/consents/status/")

    assert withdraw_guest.status_code == 201
    assert withdraw_guest.data["identity_type"] == "guest"
    assert withdraw_guest.data["consent_state"] == "required"
    assert status_guest.data == {"identity_type": "guest", "consent_state": "required"}

    user = create_verified_user("withdraw-user@example.com")
    ConsentService().accept(user=user)
    user_client = APIClient()
    user_client.force_login(user)

    withdraw_user = user_client.post("/api/consents/withdraw/", {}, format="json")
    status_user = user_client.get("/api/consents/status/")

    assert withdraw_user.status_code == 201
    assert withdraw_user.data["identity_type"] == "user"
    assert withdraw_user.data["consent_state"] == "required"
    assert status_user.data == {"identity_type": "user", "consent_state": "required"}


def test_reconsent_required_record_overrides_previous_acceptance() -> None:
    """Latest re-consent-required record makes consent state required."""

    user = create_verified_user("reconsent@example.com")
    ConsentService().accept(user=user)
    ConsentService().require_reconsent(user=user)

    assert ConsentService().state_for_identity(user=user) == "required"


def test_register_creates_otp_hash_and_does_not_expose_secret() -> None:
    """Register creates an unverified account, emails OTP, and hides OTP in response."""

    client = APIClient()
    response = client.post(
        "/api/accounts/register/",
        {"email": "new@example.com", "password": PASSWORD},
        format="json",
    )

    user = User.objects.get(email="new@example.com")
    response_text = str(response.data)

    assert response.status_code == 201
    assert response.data["email_verification_required"] is True
    assert response.data["next_action"] == "verify_email"
    assert user.email_verified is False
    assert user.email_otp_hash
    assert user.email_otp_hash not in response_text
    assert extract_otp() not in response_text
    assert len(mail.outbox) == 1


def test_register_accepts_six_character_password() -> None:
    """Register allows the configured six-character minimum password length."""

    client = APIClient()
    response = client.post(
        "/api/accounts/register/",
        {"email": "sixchar@example.com", "password": "Qw7!zP"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["email_verification_required"] is True


def test_register_password_too_short_returns_specific_code() -> None:
    """Register returns password_too_short when password is below minimum length."""

    client = APIClient()
    response = client.post(
        "/api/accounts/register/",
        {"email": "user@example.com", "password": "abc"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data == {"error": "password_too_short"}


def test_register_password_entirely_numeric_returns_specific_code() -> None:
    """Register returns password_entirely_numeric for all-digit passwords."""

    client = APIClient()
    response = client.post(
        "/api/accounts/register/",
        {"email": "numericpw@example.com", "password": "36291847"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data == {"error": "password_entirely_numeric"}


def test_register_invalid_email_returns_specific_code() -> None:
    """Register returns invalid_email for malformed email addresses."""

    client = APIClient()
    response = client.post(
        "/api/accounts/register/",
        {"email": "not-an-email", "password": "ValidPass1!"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data == {"error": "invalid_email"}


def test_register_duplicate_verified_and_unverified_email_behavior() -> None:
    """Register rejects verified duplicates and resends for unverified accounts by policy."""

    verified = create_verified_user("verified@example.com")
    client = APIClient()

    duplicate = client.post(
        "/api/accounts/register/",
        {"email": verified.email, "password": PASSWORD},
        format="json",
    )

    assert duplicate.status_code == 409
    assert duplicate.data["error"] == "email_already_registered"

    unverified = User.objects.create_user(
        email="pending@example.com",
        password=PASSWORD,
        email_verified=False,
    )
    unverified.email_otp_sent_at = timezone.now() - timedelta(seconds=61)
    unverified.save(update_fields=["email_otp_sent_at"])

    resend = client.post(
        "/api/accounts/register/",
        {"email": "pending@example.com", "password": PASSWORD},
        format="json",
    )

    assert resend.status_code == 200
    assert User.objects.filter(email="pending@example.com").count() == 1
    assert resend.data["email_verification_required"] is True


def test_verify_email_otp_success_invalid_and_expired() -> None:
    """OTP verification handles success, invalid OTP, and expiry."""

    client = APIClient()
    client.post(
        "/api/accounts/register/",
        {"email": "otp@example.com", "password": PASSWORD},
        format="json",
    )
    otp = extract_otp()

    invalid = client.post(
        "/api/accounts/verify-email/",
        {"email": "otp@example.com", "otp": "000000"},
        format="json",
    )
    success = client.post(
        "/api/accounts/verify-email/",
        {"email": "otp@example.com", "otp": otp},
        format="json",
    )

    assert invalid.status_code == 400
    assert invalid.data["error"] == "invalid_otp"
    assert success.status_code == 200
    assert success.data["next_action"] == "login"
    assert User.objects.get(email="otp@example.com").email_verified is True

    client.post(
        "/api/accounts/register/",
        {"email": "expired@example.com", "password": PASSWORD},
        format="json",
    )
    expired_user = User.objects.get(email="expired@example.com")
    expired_user.email_otp_expires_at = timezone.now() - timedelta(seconds=1)
    expired_user.save(update_fields=["email_otp_expires_at"])

    expired = client.post(
        "/api/accounts/verify-email/",
        {"email": "expired@example.com", "otp": extract_otp()},
        format="json",
    )

    assert expired.status_code == 400
    assert expired.data["error"] == "otp_expired"


def test_resend_otp_cooldown_and_cap() -> None:
    """Resend enforces cooldown and resend cap."""

    client = APIClient()
    client.post(
        "/api/accounts/register/",
        {"email": "resend@example.com", "password": PASSWORD},
        format="json",
    )

    cooldown = client.post("/api/accounts/resend-otp/", {"email": "resend@example.com"}, format="json")
    assert cooldown.status_code == 429
    assert cooldown.data["error"] == "otp_resend_cooldown"

    user = User.objects.get(email="resend@example.com")
    user.email_otp_sent_at = timezone.now() - timedelta(seconds=61)
    user.resend_count = 5
    user.save(update_fields=["email_otp_sent_at", "resend_count"])

    capped = client.post("/api/accounts/resend-otp/", {"email": "resend@example.com"}, format="json")
    assert capped.status_code == 429
    assert capped.data["error"] == "otp_resend_limit_exceeded"


def test_login_verified_unverified_invalid_and_logout() -> None:
    """Login only creates sessions for active verified users."""

    verified = create_verified_user("login@example.com")
    unverified = User.objects.create_user(
        email="unverified@example.com",
        password=PASSWORD,
        email_verified=False,
    )
    client = APIClient()

    invalid = client.post(
        "/api/accounts/login/",
        {"email": verified.email, "password": "wrong-password"},
        format="json",
    )
    blocked = client.post(
        "/api/accounts/login/",
        {"email": unverified.email, "password": PASSWORD},
        format="json",
    )
    success = client.post(
        "/api/accounts/login/",
        {"email": verified.email, "password": PASSWORD},
        format="json",
    )
    logout = client.post("/api/accounts/logout/", {}, format="json")

    assert invalid.status_code == 401
    assert invalid.data["error"] == "invalid_credentials"
    assert blocked.status_code == 403
    assert blocked.data["error"] == "email_verification_required"
    assert success.status_code == 200
    assert success.data["session_state"] == "registered"
    assert success.data["user"]["email"] == verified.email
    assert logout.status_code == 200
    assert logout.data["session_state"] == "unauthenticated"


def test_google_login_creates_session_and_user_when_unlinked(monkeypatch, settings) -> None:
    """Google login verifies a credential and creates a registered session."""

    settings.WISMO_GOOGLE_CLIENT_ID = "google-client-id"
    monkeypatch.setattr(
        "accounts.services.verify_oauth2_token",
        lambda credential, request, audience: {
            "sub": "google-sub-1",
            "email": "google-new@example.com",
            "email_verified": True,
        },
    )

    client = APIClient()
    response = client.post(
        "/api/accounts/google/login/",
        {"credential": "credential-token"},
        format="json",
    )

    user = User.objects.get(email="google-new@example.com")

    assert response.status_code == 200
    assert response.data["session_state"] == "registered"
    assert response.data["identity_type"] == "user"
    assert response.data["user"]["email"] == user.email
    assert user.google_id == "google-sub-1"
    assert user.email_verified is True


def test_google_login_links_existing_email_account_and_reuses_link(monkeypatch, settings) -> None:
    """Google login links the existing email account when claims are verified."""

    settings.WISMO_GOOGLE_CLIENT_ID = "google-client-id"
    user = User.objects.create_user(email="link@example.com", password=PASSWORD, email_verified=False)
    monkeypatch.setattr(
        "accounts.services.verify_oauth2_token",
        lambda credential, request, audience: {
            "sub": "google-sub-2",
            "email": "link@example.com",
            "email_verified": True,
        },
    )

    client = APIClient()
    response = client.post(
        "/api/accounts/google/login/",
        {"credential": "credential-token"},
        format="json",
    )

    user.refresh_from_db()

    assert response.status_code == 200
    assert response.data["user"]["email"] == user.email
    assert user.google_id == "google-sub-2"
    assert user.email_verified is True


def test_google_login_rejects_invalid_token_and_account_conflict(monkeypatch, settings) -> None:
    """Google login returns canonical keyword errors for invalid and conflicting claims."""

    settings.WISMO_GOOGLE_CLIENT_ID = "google-client-id"
    conflict_user = User.objects.create_user(
        email="conflict@example.com",
        password=PASSWORD,
        google_id="existing-sub",
        email_verified=True,
    )
    client = APIClient()

    def raise_bad_token(*args, **kwargs):
        """Raise a token verification failure for the invalid credential path."""

        raise ValueError("bad token")

    monkeypatch.setattr("accounts.services.verify_oauth2_token", raise_bad_token)
    invalid = client.post(
        "/api/accounts/google/login/",
        {"credential": "bad-credential"},
        format="json",
    )

    monkeypatch.setattr(
        "accounts.services.verify_oauth2_token",
        lambda credential, request, audience: {
            "sub": "new-google-sub",
            "email": conflict_user.email,
            "email_verified": True,
        },
    )
    conflict = client.post(
        "/api/accounts/google/login/",
        {"credential": "credential-token"},
        format="json",
    )

    assert invalid.status_code == 401
    assert invalid.data["error"] == "invalid_credentials"
    assert conflict.status_code == 409
    assert conflict.data["error"] == "google_account_conflict"


def test_request_gate_identity_session_consent_and_success_paths() -> None:
    """Request gate uses the canonical identity and consent service paths."""

    anonymous = APIClient()
    missing_identity = anonymous.post(
        "/api/chat/message/",
        {"message": "hello"},
        format="json",
    )
    assert missing_identity.status_code == 401
    assert missing_identity.data["error"] == "identity_not_resolved"

    expired_guest = GuestIdentity.objects.create(expires_at=timezone.now() - timedelta(minutes=1))
    expired_client = api_client_with_guest(expired_guest)
    expired = expired_client.post(
        "/api/chat/message/",
        {"message": "hello"},
        format="json",
    )
    assert expired.status_code == 401
    assert expired.data["error"] == "guest_session_expired"

    guest = GuestIdentity.objects.create()
    guest_client = api_client_with_guest(guest)
    no_consent = guest_client.post(
        "/api/chat/message/",
        {"message": "hello"},
        format="json",
    )
    assert no_consent.status_code == 403
    assert no_consent.data["error"] == "consent_required"

    ConsentService().accept(guest_identity=guest)
    accepted = guest_client.post(
        "/api/chat/message/",
        {"message": "hello"},
        format="json",
    )
    assert accepted.status_code == 200
    assert accepted["Content-Type"] == "text/event-stream"
    events = parse_sse_stream(b"".join(accepted.streaming_content))
    done = next(e for e in events if e["type"] == "done")
    response_event = next(e for e in events if e["type"] == "response")
    assert done["data"]["chat_id"]
    assert response_event["data"]["text"]


def test_request_gate_validation_errors() -> None:
    """Request gate returns canonical validation errors before runtime."""

    client = APIClient()
    guest = GuestIdentity.objects.create()
    gated_client = api_client_with_guest(guest)
    ConsentService().accept(guest_identity=guest)

    missing = client.post("/api/chat/message/", {}, format="json")
    invalid_chat = client.post(
        "/api/chat/message/",
        {"message": "hello", "chat_id": "not-a-uuid"},
        format="json",
    )
    empty = gated_client.post(
        "/api/chat/message/",
        {"message": "   "},
        format="json",
    )
    too_long = gated_client.post(
        "/api/chat/message/",
        {"message": "x" * 8001},
        format="json",
    )
    too_large = gated_client.post(
        "/api/chat/message/",
        {"message": "x", "padding": "y" * 70000},
        format="json",
    )

    assert missing.status_code == 400
    assert missing.data["error"] == "missing_required_field"
    assert invalid_chat.status_code == 400
    assert invalid_chat.data["error"] == "invalid_chat_id"
    assert empty.status_code == 400
    assert empty.data["error"] == "empty_message"
    assert too_long.status_code == 413
    assert too_long.data["error"] == "message_too_long"
    assert too_large.status_code == 413
    assert too_large.data["error"] == "payload_too_large"


def test_request_gate_registered_identity_clears_stale_guest_cookie() -> None:
    """Registered identity is canonical and clears stale guest cookies."""

    user = create_verified_user("canonical@example.com")
    guest = GuestIdentity.objects.create()

    client = api_client_with_guest(guest)
    client.force_login(user)
    blocked = client.post(
        "/api/chat/message/",
        {"message": "hello"},
        format="json",
    )

    ConsentService().accept(user=user)
    client.cookies[GUEST_COOKIE_NAME] = str(guest.id)
    allowed = client.post(
        "/api/chat/message/",
        {"message": "hello"},
        format="json",
    )

    assert blocked.status_code == 403
    assert blocked.data["error"] == "consent_required"
    assert blocked.cookies[GUEST_COOKIE_NAME]["max-age"] == 0
    assert allowed.status_code == 200
    assert allowed["Content-Type"] == "text/event-stream"
    assert allowed.cookies[GUEST_COOKIE_NAME]["max-age"] == 0


def test_request_gate_previous_turn_barrier() -> None:
    """Request gate blocks new turns while previous turn finalization is pending."""

    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    chat = Chat.objects.create(guest_identity=guest)
    case = Case.objects.create(guest_identity=guest, topic="case")
    chat.case = case
    chat.save(update_fields=["case", "updated_at"])

    barrier_turn = ChatTurn.objects.create(
        guest_identity=guest,
        chat=chat,
        case=case,
        user_message_text="hello",
        status="completed",
    )
    barrier_turn.step12_finalization_status = "processing"
    barrier_turn.save(update_fields=["step12_finalization_status"])

    client = api_client_with_guest(guest)
    blocked_by_barrier = client.post(
        "/api/chat/message/",
        {"message": "hello", "chat_id": str(chat.id)},
        format="json",
    )

    assert blocked_by_barrier.status_code == 409
    assert blocked_by_barrier.data["error"] == "turn_in_progress"


def test_request_gate_quota_failures_append_pending_input() -> None:
    """Quota failures append pending input on the current quota window."""

    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    guest_quota = UsageQuotaWindow.current_for_identity(guest_identity=guest)
    guest_quota.is_exhausted = True
    guest_quota.save(update_fields=["is_exhausted", "updated_at"])

    guest_response = api_client_with_guest(guest).post(
        "/api/chat/message/",
        {"message": "guest blocked"},
        format="json",
    )
    guest_quota.refresh_from_db()

    user = create_verified_user("quota-user@example.com")
    ConsentService().accept(user=user)
    user_quota = UsageQuotaWindow.current_for_identity(user=user)
    user_quota.is_exhausted = True
    user_quota.save(update_fields=["is_exhausted", "updated_at"])

    user_client = APIClient()
    user_client.force_login(user)
    user_response = user_client.post(
        "/api/chat/message/",
        {"message": "user blocked"},
        format="json",
    )
    user_quota.refresh_from_db()

    assert guest_response.status_code == 429
    assert guest_response.data["error"] == "registration_required_by_quota"
    assert "guest blocked" in guest_quota.pending_input_text
    assert guest_quota.pending_input_append_count == 1
    assert guest_quota.pending_input_updated_at is not None

    assert user_response.status_code == 429
    assert user_response.data["error"] == "quota_exceeded"
    assert "user blocked" in user_quota.pending_input_text
    assert user_quota.pending_input_append_count == 1
    assert user_quota.pending_input_updated_at is not None


def test_request_gate_chat_not_found_and_access_denied() -> None:
    """Ownership check distinguishes unavailable chats from foreign chats."""

    current_guest = GuestIdentity.objects.create()
    other_guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=current_guest)
    archived_chat = Chat.objects.create(guest_identity=current_guest, is_archived=True)
    foreign_chat = Chat.objects.create(guest_identity=other_guest)
    client = api_client_with_guest(current_guest)

    missing = client.post(
        "/api/chat/message/",
        {"message": "hello", "chat_id": str(archived_chat.id)},
        format="json",
    )
    denied = client.post(
        "/api/chat/message/",
        {"message": "hello", "chat_id": str(foreign_chat.id)},
        format="json",
    )

    assert missing.status_code == 404
    assert missing.data["error"] == "chat_not_found"
    assert denied.status_code == 403
    assert denied.data["error"] == "chat_access_denied"


# --- BE-11: guest idle TTL, mark_seen placement, and auto-attach tests ---


def test_create_guest_sets_expires_at() -> None:
    """Guest created via /api/accounts/guest/init/ has a non-null expires_at."""

    response = APIClient().post("/api/accounts/guest/init/", {}, format="json")

    assert response.status_code == 201
    guest_id = response.data["guest_token"]
    guest = GuestIdentity.objects.get(id=guest_id)
    assert guest.expires_at is not None


def test_mark_seen_updates_last_seen_at_and_expires_at() -> None:
    """mark_seen() updates both last_seen_at and extends expires_at."""

    before = timezone.now()
    guest = GuestIdentity.objects.create()
    guest.mark_seen()
    guest.refresh_from_db()

    assert guest.last_seen_at >= before
    assert guest.expires_at is not None
    assert guest.expires_at > timezone.now()


def test_session_status_does_not_call_mark_seen() -> None:
    """session_status() does not extend guest expires_at (not a message-send action)."""

    original_expires = timezone.now() + timedelta(hours=3)
    guest = GuestIdentity.objects.create(expires_at=original_expires)
    client = api_client_with_guest(guest)

    client.get("/api/accounts/session/")

    guest.refresh_from_db()
    # expires_at must not have moved forward
    assert abs((guest.expires_at - original_expires).total_seconds()) < 1


def test_resolve_bootstrap_identity_does_not_call_mark_seen() -> None:
    """Chat bootstrap endpoint does not extend guest expires_at."""

    original_expires = timezone.now() + timedelta(hours=3)
    guest = GuestIdentity.objects.create(expires_at=original_expires)
    ConsentService().accept(guest_identity=guest)
    client = api_client_with_guest(guest)

    client.get("/api/chat/")

    guest.refresh_from_db()
    assert abs((guest.expires_at - original_expires).total_seconds()) < 1


def test_gate_calls_mark_seen_even_when_consent_not_accepted() -> None:
    """Gate extends guest TTL on message send even if gate fails at consent step."""

    guest = GuestIdentity.objects.create(expires_at=timezone.now() + timedelta(hours=1))
    before = timezone.now()
    client = api_client_with_guest(guest)

    response = client.post("/api/chat/message/", {"message": "hello"}, format="json")

    assert response.status_code == 403
    assert response.data["error"] == "consent_required"
    guest.refresh_from_db()
    # expires_at must have been pushed forward by mark_seen()
    assert guest.expires_at > before + timedelta(hours=1)


def test_gate_mark_seen_updates_expires_at_even_on_consent_failure() -> None:
    """Sending a message updates guest expires_at regardless of gate outcome."""

    initial_expires = timezone.now() + timedelta(minutes=30)
    guest = GuestIdentity.objects.create(expires_at=initial_expires)
    client = api_client_with_guest(guest)

    client.post("/api/chat/message/", {"message": "hello"}, format="json")

    guest.refresh_from_db()
    assert guest.expires_at > initial_expires


def test_verify_email_auto_attaches_guest_chat_and_clears_cookie() -> None:
    """VerifyEmailView silently attaches eligible guest chat after OTP verify."""

    client = APIClient()
    client.post("/api/accounts/register/", {"email": "autoattach@example.com", "password": PASSWORD}, format="json")
    otp = extract_otp()

    guest = GuestIdentity.objects.create(expires_at=timezone.now() + timedelta(hours=6))
    ConsentService().accept(guest_identity=guest)
    case = Case.objects.create(guest_identity=guest, topic="guest case")
    chat = Chat.objects.create(guest_identity=guest, case=case, opening_input_text="hi")

    client.cookies[GUEST_COOKIE_NAME] = str(guest.id)
    response = client.post(
        "/api/accounts/verify-email/",
        {"email": "autoattach@example.com", "otp": otp},
        format="json",
    )

    chat.refresh_from_db()
    case.refresh_from_db()
    user = User.objects.get(email="autoattach@example.com")

    assert response.status_code == 200
    assert response.data["email_verified"] is True
    assert chat.user_id == user.id
    assert chat.guest_identity_id is None
    assert case.user_id == user.id
    assert case.guest_identity_id is None
    # Cookie must be cleared
    assert response.cookies.get(GUEST_COOKIE_NAME, {}).get("max-age") == 0


def test_verify_email_succeeds_when_guest_has_no_eligible_chat() -> None:
    """VerifyEmailView returns 200 when guest has no active unarchived chat to attach."""

    client = APIClient()
    client.post("/api/accounts/register/", {"email": "noattach@example.com", "password": PASSWORD}, format="json")
    otp = extract_otp()

    guest = GuestIdentity.objects.create(expires_at=timezone.now() + timedelta(hours=6))
    client.cookies[GUEST_COOKIE_NAME] = str(guest.id)

    response = client.post(
        "/api/accounts/verify-email/",
        {"email": "noattach@example.com", "otp": otp},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["email_verified"] is True
    # No cookie clearing when no attach happened
    assert GUEST_COOKIE_NAME not in response.cookies or response.cookies.get(GUEST_COOKIE_NAME, {}).get("max-age") != 0


def test_verify_email_succeeds_when_attach_raises_exception(monkeypatch) -> None:
    """VerifyEmailView returns 200 even when GuestAttachService raises during auto-attach."""

    from accounts.services import GuestAttachService

    client = APIClient()
    client.post("/api/accounts/register/", {"email": "attachfail@example.com", "password": PASSWORD}, format="json")
    otp = extract_otp()

    guest = GuestIdentity.objects.create(expires_at=timezone.now() + timedelta(hours=6))
    case = Case.objects.create(guest_identity=guest, topic="fail case")
    Chat.objects.create(guest_identity=guest, case=case)
    client.cookies[GUEST_COOKIE_NAME] = str(guest.id)

    def raise_always(self, **kwargs):
        raise RuntimeError("attach boom")

    monkeypatch.setattr(GuestAttachService, "attach_current_case", raise_always)

    response = client.post(
        "/api/accounts/verify-email/",
        {"email": "attachfail@example.com", "otp": otp},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["email_verified"] is True
