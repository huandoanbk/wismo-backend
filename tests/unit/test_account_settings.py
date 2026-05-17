"""Tests for AccountSettingsService and account settings/privacy endpoints."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from accounts.constants import ANONYMOUS_USER_ID
from accounts.models import User
from accounts.services import AccountServiceError, AccountSettingsService
from chat.models import Case, Chat, ChatTurn
from memory.models import MemoryItem

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ng-Uncommon-Passphrase-2026!"


def create_verified_user(email: str = "user@example.com", password: str = PASSWORD) -> User:
    """Create a verified registered user."""

    return User.objects.create_user(email=email, password=password, email_verified=True)


def authenticated_client(user: User) -> APIClient:
    """Return an API client with an active session for the given user."""

    client = APIClient()
    client.force_login(user)
    return client


# ---------------------------------------------------------------------------
# Unit tests: get_profile
# ---------------------------------------------------------------------------

def test_get_profile_returns_all_fields() -> None:
    user = create_verified_user()
    profile = AccountSettingsService().get_profile(user)
    assert profile["email"] == user.email
    assert profile["display_name"] == user.display_name
    assert profile["email_verified"] is True
    assert "date_joined" in profile
    # ISO 8601 UTC format
    assert profile["date_joined"].endswith("Z")
    assert "T" in profile["date_joined"]


# ---------------------------------------------------------------------------
# Unit tests: update_display_name
# ---------------------------------------------------------------------------

def test_update_display_name_happy_path() -> None:
    user = create_verified_user()
    profile = AccountSettingsService().update_display_name(user, "New Name")
    assert profile["display_name"] == "New Name"
    user.refresh_from_db()
    assert user.display_name == "New Name"


def test_update_display_name_empty_string() -> None:
    user = create_verified_user()
    user.display_name = "Old"
    user.save()
    profile = AccountSettingsService().update_display_name(user, "")
    assert profile["display_name"] == ""
    user.refresh_from_db()
    assert user.display_name == ""


def test_update_display_name_too_long() -> None:
    user = create_verified_user()
    with pytest.raises(AccountServiceError) as exc_info:
        AccountSettingsService().update_display_name(user, "x" * 256)
    assert exc_info.value.code == "display_name_too_long"
    assert exc_info.value.status_code == 400


def test_update_display_name_non_string() -> None:
    user = create_verified_user()
    with pytest.raises(AccountServiceError) as exc_info:
        AccountSettingsService().update_display_name(user, 123)  # type: ignore[arg-type]
    assert exc_info.value.code == "invalid_request"


# ---------------------------------------------------------------------------
# Unit tests: change_password
# ---------------------------------------------------------------------------

class FakeRequest:
    """Minimal request stub for update_session_auth_hash."""

    class _Session(dict):
        def cycle_key(self) -> None:
            pass

        def __setitem__(self, key, value) -> None:
            pass

    def __init__(self, user=None):
        self.session = self._Session()
        self.user = user


def test_change_password_happy_path() -> None:
    user = create_verified_user(password="OldPass-Secure-2026!")
    AccountSettingsService().change_password(
        FakeRequest(user), user, "OldPass-Secure-2026!", "NewPass-Secure-2026!"
    )
    user.refresh_from_db()
    assert user.check_password("NewPass-Secure-2026!")


def test_change_password_wrong_current() -> None:
    user = create_verified_user()
    with pytest.raises(AccountServiceError) as exc_info:
        AccountSettingsService().change_password(FakeRequest(user), user, "wrong!", PASSWORD)
    assert exc_info.value.code == "invalid_current_password"


def test_change_password_weak_new_password() -> None:
    user = create_verified_user()
    with pytest.raises(AccountServiceError):
        AccountSettingsService().change_password(FakeRequest(user), user, PASSWORD, "123")


def test_change_password_google_only_account() -> None:
    user = User.objects.create_user(email="google@example.com", email_verified=True)
    user.set_unusable_password()
    user.save()
    with pytest.raises(AccountServiceError) as exc_info:
        AccountSettingsService().change_password(FakeRequest(user), user, "any", "any")
    assert exc_info.value.code == "no_usable_password"


# ---------------------------------------------------------------------------
# Unit tests: erase_all_chat_data
# ---------------------------------------------------------------------------

def test_erase_all_chat_data_happy_path() -> None:
    user = create_verified_user()
    sentinel = User.objects.get(id=ANONYMOUS_USER_ID)

    case = Case.objects.create(user=user, topic="topic", context_summary="summary")
    chat = Chat.objects.create(user=user, case=case)
    turn = ChatTurn.objects.create(
        chat=chat, case=case, user=user,
        user_message_text="hello", assistant_response_text="hi",
    )
    memory = MemoryItem.objects.create(
        user=user, case=case, memory_type="profile_fact", normalized_text="fact"
    )

    AccountSettingsService().erase_all_chat_data(user)

    case.refresh_from_db()
    assert case.user == sentinel
    assert case.guest_identity is None
    assert case.context_summary == ""
    assert case.topic == ""

    chat.refresh_from_db()
    assert chat.user == sentinel
    assert chat.guest_identity is None
    assert chat.is_archived is True

    turn.refresh_from_db()
    assert turn.user == sentinel
    assert turn.guest_identity is None
    assert turn.user_message_text == ""
    assert turn.assistant_response_text == ""

    memory.refresh_from_db()
    assert memory.user == sentinel
    assert memory.case is None


def test_erase_all_chat_data_idempotent_no_data() -> None:
    user = create_verified_user()
    # Should not raise even with no chats/cases/memory
    AccountSettingsService().erase_all_chat_data(user)


# ---------------------------------------------------------------------------
# Integration tests: GET /api/accounts/me/
# ---------------------------------------------------------------------------

def test_get_me_authenticated() -> None:
    user = create_verified_user(email="me@example.com")
    client = authenticated_client(user)
    response = client.get("/api/accounts/me/")
    assert response.status_code == 200
    assert response.data["email"] == "me@example.com"
    assert "display_name" in response.data
    assert "email_verified" in response.data
    assert "date_joined" in response.data


def test_get_me_unauthenticated() -> None:
    client = APIClient()
    response = client.get("/api/accounts/me/")
    assert response.status_code == 403  # DRF IsAuthenticated returns 403 for anonymous


# ---------------------------------------------------------------------------
# Integration tests: PATCH /api/accounts/me/
# ---------------------------------------------------------------------------

def test_patch_me_update_display_name() -> None:
    user = create_verified_user()
    client = authenticated_client(user)
    response = client.patch("/api/accounts/me/", {"display_name": "Updated"}, format="json")
    assert response.status_code == 200
    assert response.data["display_name"] == "Updated"


def test_patch_me_empty_string() -> None:
    user = create_verified_user()
    client = authenticated_client(user)
    response = client.patch("/api/accounts/me/", {"display_name": ""}, format="json")
    assert response.status_code == 200
    assert response.data["display_name"] == ""


def test_patch_me_too_long() -> None:
    user = create_verified_user()
    client = authenticated_client(user)
    response = client.patch("/api/accounts/me/", {"display_name": "x" * 256}, format="json")
    assert response.status_code == 400
    assert response.data["error"] == "display_name_too_long"


def test_patch_me_non_string_display_name() -> None:
    user = create_verified_user()
    client = authenticated_client(user)
    response = client.patch("/api/accounts/me/", {"display_name": 123}, format="json")
    assert response.status_code == 400
    assert response.data["error"] == "invalid_request"


def test_patch_me_unauthenticated() -> None:
    client = APIClient()
    response = client.patch("/api/accounts/me/", {"display_name": "x"}, format="json")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Integration tests: POST /api/accounts/change-password/
# ---------------------------------------------------------------------------

def test_change_password_success() -> None:
    user = create_verified_user(password="OldPass-Secure-2026!")
    client = authenticated_client(user)
    response = client.post(
        "/api/accounts/change-password/",
        {"current_password": "OldPass-Secure-2026!", "new_password": "NewPass-Secure-2026!"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["password_changed"] is True
    user.refresh_from_db()
    assert user.check_password("NewPass-Secure-2026!")


def test_change_password_wrong_current_integration() -> None:
    user = create_verified_user()
    client = authenticated_client(user)
    response = client.post(
        "/api/accounts/change-password/",
        {"current_password": "wrong!", "new_password": "NewPass-Secure-2026!"},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["error"] == "invalid_current_password"


def test_change_password_weak_new() -> None:
    user = create_verified_user()
    client = authenticated_client(user)
    response = client.post(
        "/api/accounts/change-password/",
        {"current_password": PASSWORD, "new_password": "123"},
        format="json",
    )
    assert response.status_code == 400


def test_change_password_google_only() -> None:
    user = User.objects.create_user(email="google2@example.com", email_verified=True)
    user.set_unusable_password()
    user.save()
    client = authenticated_client(user)
    response = client.post(
        "/api/accounts/change-password/",
        {"current_password": "any", "new_password": "NewPass-Secure-2026!"},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["error"] == "no_usable_password"


def test_change_password_missing_field() -> None:
    user = create_verified_user()
    client = authenticated_client(user)
    response = client.post(
        "/api/accounts/change-password/",
        {"current_password": PASSWORD},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["error"] == "invalid_request"


def test_change_password_unauthenticated() -> None:
    client = APIClient()
    response = client.post(
        "/api/accounts/change-password/",
        {"current_password": PASSWORD, "new_password": "x"},
        format="json",
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Integration tests: POST /api/accounts/delete-all-chat/
# ---------------------------------------------------------------------------

def test_delete_all_chat_success_and_data_scrubbed() -> None:
    user = create_verified_user()
    sentinel = User.objects.get(id=ANONYMOUS_USER_ID)

    case = Case.objects.create(user=user, topic="t", context_summary="s")
    chat = Chat.objects.create(user=user, case=case)
    ChatTurn.objects.create(
        chat=chat, case=case, user=user,
        user_message_text="msg", assistant_response_text="resp",
    )
    MemoryItem.objects.create(
        user=user, case=case, memory_type="theme", normalized_text="fact"
    )

    client = authenticated_client(user)
    response = client.post("/api/accounts/delete-all-chat/")
    assert response.status_code == 200
    assert response.data["erased"] is True

    case.refresh_from_db()
    assert case.user == sentinel
    chat.refresh_from_db()
    assert chat.user == sentinel
    assert chat.is_archived is True


def test_delete_all_chat_no_data_idempotent() -> None:
    user = create_verified_user(email="empty@example.com")
    client = authenticated_client(user)
    response = client.post("/api/accounts/delete-all-chat/")
    assert response.status_code == 200
    assert response.data["erased"] is True


def test_delete_all_chat_unauthenticated() -> None:
    client = APIClient()
    response = client.post("/api/accounts/delete-all-chat/")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Unit tests: add_password
# ---------------------------------------------------------------------------

def test_add_password_happy_path() -> None:
    user = User.objects.create_user(email="google3@example.com", email_verified=True)
    user.set_unusable_password()
    user.save()
    AccountSettingsService().add_password(user, "NewPass-Secure-2026!")
    user.refresh_from_db()
    assert user.check_password("NewPass-Secure-2026!")


def test_add_password_already_has_password() -> None:
    user = create_verified_user()
    with pytest.raises(AccountServiceError) as exc_info:
        AccountSettingsService().add_password(user, "AnyPass-Secure-2026!")
    assert exc_info.value.code == "already_has_password"
    assert exc_info.value.status_code == 400


def test_add_password_weak_password() -> None:
    user = User.objects.create_user(email="google4@example.com", email_verified=True)
    user.set_unusable_password()
    user.save()
    with pytest.raises(AccountServiceError):
        AccountSettingsService().add_password(user, "123")


# ---------------------------------------------------------------------------
# Integration tests: POST /api/accounts/add-password/
# ---------------------------------------------------------------------------

def test_add_password_success() -> None:
    user = User.objects.create_user(email="google5@example.com", email_verified=True)
    user.set_unusable_password()
    user.save()
    client = authenticated_client(user)
    response = client.post(
        "/api/accounts/add-password/",
        {"new_password": "NewPass-Secure-2026!"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["password_added"] is True
    user.refresh_from_db()
    assert user.check_password("NewPass-Secure-2026!")


def test_add_password_already_has_password_integration() -> None:
    user = create_verified_user()
    client = authenticated_client(user)
    response = client.post(
        "/api/accounts/add-password/",
        {"new_password": "AnyPass-Secure-2026!"},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["error"] == "already_has_password"


def test_add_password_weak_integration() -> None:
    user = User.objects.create_user(email="google6@example.com", email_verified=True)
    user.set_unusable_password()
    user.save()
    client = authenticated_client(user)
    response = client.post(
        "/api/accounts/add-password/",
        {"new_password": "123"},
        format="json",
    )
    assert response.status_code == 400


def test_add_password_missing_field() -> None:
    user = User.objects.create_user(email="google7@example.com", email_verified=True)
    user.set_unusable_password()
    user.save()
    client = authenticated_client(user)
    response = client.post("/api/accounts/add-password/", {}, format="json")
    assert response.status_code == 400
    assert response.data["error"] == "invalid_request"


def test_add_password_unauthenticated() -> None:
    client = APIClient()
    response = client.post(
        "/api/accounts/add-password/",
        {"new_password": "NewPass-Secure-2026!"},
        format="json",
    )
    assert response.status_code == 403
