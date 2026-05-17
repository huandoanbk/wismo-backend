"""Identity, guest, OTP auth, and attach services for the MVP baseline."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.id_token import verify_oauth2_token

from accounts.models import GuestIdentity, User
from chat.models import Case, Chat, ChatTurn
from chat.services import IdentityContext
from consents.services import ConsentService
from runtime.models import UsageQuotaWindow
from wismo.contracts.codes import (
    GUEST_CHAT_NOT_FOUND,
    IDENTITY_NOT_RESOLVED,
    INVALID_CHAT_ID,
    INVALID_REQUEST,
    SESSION_EXPIRED,
    SESSION_REQUIRED,
)

GUEST_COOKIE_NAME = "wismo_guest"
GUEST_HEADER_NAME = "X-Guest-Token"


class AccountServiceError(Exception):
    """Domain error surfaced by account API views."""

    def __init__(self, code: str, status_code: int = 400, message: str = "") -> None:
        """Create an account service error with API status metadata."""

        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class OtpIssueResult:
    """Result of issuing an email verification OTP."""

    user: User
    otp_expires_at: Any
    created: bool = False


@dataclass(frozen=True)
class AttachResult:
    """Result of attaching a guest-owned case to a registered user."""

    chat_id: uuid.UUID
    case_id: uuid.UUID | None
    transferred_chat_count: int
    transferred_turn_count: int


@dataclass(frozen=True)
class GoogleLoginResult:
    """Result of verifying a Google credential and creating a session."""

    user: User
    created: bool = False
    linked: bool = False


class IdentityService:
    """Resolve identity/session state shared by APIs and request gate."""

    def create_guest(self, *, request) -> GuestIdentity:
        """Create a guest identity for the current browser/BFF session."""

        session = getattr(request, "session", None)
        session_key = getattr(session, "session_key", "") or ""
        from runtime.services import RuntimeConfigService

        ttl_hours = RuntimeConfigService().guest_session_policy().idle_ttl_hours
        expires_at = timezone.now() + timedelta(hours=ttl_hours)
        return GuestIdentity.objects.create(session_key=session_key, expires_at=expires_at)

    def guest_token_from_request(self, request) -> str | None:
        """Return the guest token carried by cookie or BFF/test header."""

        return request.COOKIES.get(GUEST_COOKIE_NAME) or request.headers.get(GUEST_HEADER_NAME)

    def guest_from_request(self, request) -> GuestIdentity | None:
        """Resolve a guest record from request without enforcing active/expiry state."""

        guest_token = self.guest_token_from_request(request)
        if not guest_token:
            return None

        try:
            guest_id = uuid.UUID(str(guest_token))
        except ValueError:
            return None

        return GuestIdentity.objects.filter(id=guest_id).first()

    def is_guest_valid(self, guest: GuestIdentity) -> bool:
        """Return whether the guest identity can be used for runtime."""

        if not guest.is_active:
            return False
        return guest.expires_at is None or guest.expires_at > timezone.now()

    def resolve_for_gate(self, request) -> IdentityContext:
        """Resolve the request gate identity without checking consent/quota.

        session_expired is raised only when the user IS authenticated but their
        account is inactive or unverified — not for Django session TTL expiry.
        When Django session TTL expires the user becomes AnonymousUser; with no
        guest cookie that falls through to IDENTITY_NOT_RESOLVED. Both codes
        tell the FE to redirect to login.
        """

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            if user.is_active and user.email_verified:
                user.last_seen_at = timezone.now()
                user.save(update_fields=["last_seen_at"])
                return IdentityContext(user=user)
            raise AccountServiceError(SESSION_EXPIRED, 401)

        guest = self.guest_from_request(request)
        if guest is None:
            raise AccountServiceError(IDENTITY_NOT_RESOLVED, 401)
        return IdentityContext(guest_identity=guest)

    def session_status(self, *, request) -> dict[str, Any]:
        """Return canonical session and consent state for FE/BFF."""

        consent_service = ConsentService()
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            if user.is_active and user.email_verified:
                user.last_seen_at = timezone.now()
                user.save(update_fields=["last_seen_at"])
                return {
                    "session_state": "registered",
                    "identity_type": "user",
                    "user": self.user_payload(user),
                    "consent_state": consent_service.state_for_identity(user=user),
                }
            # Account is authenticated but deactivated or unverified — mirrors SESSION_EXPIRED from gate.
            return {
                "session_state": "session_expired",
                "identity_type": "user",
                "user": self.user_payload(user),
                "consent_state": "unknown",
            }

        guest = self.guest_from_request(request)
        if guest is not None and self.is_guest_valid(guest):
            return {
                "session_state": "guest",
                "identity_type": "guest",
                "guest": self.guest_payload(guest),
                "consent_state": consent_service.state_for_identity(guest_identity=guest),
            }

        return {
            "session_state": "unauthenticated",
            "identity_type": "none",
            "consent_state": "unknown",
        }

    @staticmethod
    def user_payload(user: User) -> dict[str, str | bool]:
        """Serialize minimal registered identity metadata."""

        return {
            "email": user.email,
            "display_name": user.display_name,
            "email_verified": user.email_verified,
        }

    @staticmethod
    def guest_payload(guest: GuestIdentity) -> dict[str, str]:
        """Serialize minimal guest identity metadata."""

        return {"id": str(guest.id)}


class AccountAuthService:
    """Manage email/password registration, OTP verification, and login sessions."""

    def register(self, *, email: str, password: str, display_name: str = "") -> OtpIssueResult:
        """Create or update an unverified user and issue an OTP."""

        normalized_email = self.normalize_email(email)
        self.validate_registration_payload(normalized_email, password, display_name)

        user = User.objects.filter(email__iexact=normalized_email).first()
        if user is not None and user.email_verified:
            raise AccountServiceError("email_already_registered", 409)

        if user is None:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=normalized_email,
                    password=password,
                    display_name=display_name.strip(),
                    email_verified=False,
                )
                otp_result = self.issue_otp(user=user, enforce_cooldown=False, increment_resend=False)
            return OtpIssueResult(user=user, otp_expires_at=otp_result.otp_expires_at, created=True)

        with transaction.atomic():
            user.email = normalized_email
            user.display_name = display_name.strip() or user.display_name
            user.set_password(password)
            user.save(update_fields=["email", "display_name", "password"])
            otp_result = self.issue_otp(user=user, enforce_cooldown=True, increment_resend=True)
        return OtpIssueResult(user=user, otp_expires_at=otp_result.otp_expires_at, created=False)

    def resend_otp(self, *, email: str) -> OtpIssueResult:
        """Issue a new OTP for an existing unverified account."""

        user = self.get_user_by_email(email)
        if user.email_verified:
            raise AccountServiceError("email_already_verified", 409)
        return self.issue_otp(user=user, enforce_cooldown=True, increment_resend=True)

    def verify_email(self, *, email: str, otp: str) -> User:
        """Verify an unverified user by OTP."""

        user = self.get_user_by_email(email)
        if user.email_verified:
            return user
        if not user.email_otp_hash or not user.email_otp_expires_at:
            raise AccountServiceError("invalid_otp", 400)
        if user.email_otp_expires_at <= timezone.now():
            raise AccountServiceError("otp_expired", 400)
        if not check_password(str(otp).strip(), user.email_otp_hash):
            raise AccountServiceError("invalid_otp", 400)

        user.email_verified = True
        user.email_otp_hash = None
        user.email_otp_expires_at = None
        user.email_otp_sent_at = None
        user.resend_count = 0
        user.save(
            update_fields=[
                "email_verified",
                "email_otp_hash",
                "email_otp_expires_at",
                "email_otp_sent_at",
                "resend_count",
            ]
        )
        return user

    def login(self, *, request, email: str, password: str) -> User:
        """Create a Django session for a verified active user."""

        user = User.objects.filter(email__iexact=self.normalize_email(email)).first()
        if user is None or not user.is_active or not user.check_password(password):
            raise AccountServiceError("invalid_credentials", 401)
        if not user.email_verified:
            raise AccountServiceError("email_verification_required", 403)

        django_login(request, user)
        request.user = user
        user.last_seen_at = timezone.now()
        user.save(update_fields=["last_seen_at"])
        return user

    def login_with_google(self, *, request, credential: str) -> GoogleLoginResult:
        """Verify a Google ID token and create a Django session."""

        normalized_credential = self._required_google_credential(credential)
        payload = self.verify_google_credential(normalized_credential)
        user, created, linked = self.resolve_google_user(payload)

        django_login(request, user)
        request.user = user
        user.last_seen_at = timezone.now()
        user.save(update_fields=["last_seen_at"])
        return GoogleLoginResult(user=user, created=created, linked=linked)

    def logout(self, *, request) -> None:
        """Clear the current Django session."""

        django_logout(request)
        request.user = AnonymousUser()

    def issue_otp(
        self,
        *,
        user: User,
        enforce_cooldown: bool,
        increment_resend: bool,
    ) -> OtpIssueResult:
        """Generate, persist, and email an OTP for an unverified user."""

        now = timezone.now()
        cooldown_seconds = settings.WISMO_OTP_RESEND_COOLDOWN_SECONDS
        if enforce_cooldown and user.email_otp_sent_at is not None:
            elapsed = (now - user.email_otp_sent_at).total_seconds()
            if elapsed < cooldown_seconds:
                raise AccountServiceError("otp_resend_cooldown", 429)

        if increment_resend and user.resend_count >= settings.WISMO_OTP_RESEND_CAP:
            raise AccountServiceError("otp_resend_limit_exceeded", 429)

        otp = self.generate_otp()
        user.email_otp_hash = make_password(otp)
        user.email_otp_expires_at = now + timedelta(minutes=settings.WISMO_OTP_TTL_MINUTES)
        user.email_otp_sent_at = now
        if increment_resend:
            user.resend_count += 1
        else:
            user.resend_count = 0
        user.save(
            update_fields=[
                "email_otp_hash",
                "email_otp_expires_at",
                "email_otp_sent_at",
                "resend_count",
            ]
        )
        self.send_otp_email(user=user, otp=otp)
        return OtpIssueResult(user=user, otp_expires_at=user.email_otp_expires_at)

    def send_otp_email(self, *, user: User, otp: str) -> None:
        """Send the OTP through Django's configured email backend."""

        message = (
            f"Your WISMO verification code is {otp}.\n\n"
            f"This code expires in {settings.WISMO_OTP_TTL_MINUTES} minutes."
        )
        send_mail(
            subject=settings.WISMO_OTP_EMAIL_SUBJECT,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )

    def generate_otp(self) -> str:
        """Generate a zero-padded numeric OTP with configured length."""

        length = settings.WISMO_OTP_LENGTH
        maximum = 10**length
        return f"{secrets.randbelow(maximum):0{length}d}"

    def get_user_by_email(self, email: str) -> User:
        """Look up a user by normalized email or raise a public API error."""

        normalized_email = self.normalize_email(email)
        user = User.objects.filter(email__iexact=normalized_email).first()
        if user is None:
            raise AccountServiceError("user_not_found", 404)
        return user

    # Maps Django built-in password validator codes to public API error codes.
    _PASSWORD_ERROR_CODE_MAP: dict[str, str] = {
        "password_too_short": "password_too_short",
        "password_too_similar": "password_too_similar",
        "password_too_common": "password_too_common",
        "password_entirely_numeric": "password_entirely_numeric",
    }

    def validate_registration_payload(
        self,
        email: str,
        password: str,
        display_name: str,
    ) -> None:
        """Validate registration fields before persistence.

        Raises specific error codes per validation failure so callers can
        surface actionable messages without parsing free-form text.
        """

        try:
            validate_email(email)
        except ValidationError as exc:
            raise AccountServiceError("invalid_email", 400) from exc

        try:
            candidate = User(email=email, display_name=display_name.strip())
            validate_password(password, user=candidate)
        except ValidationError as exc:
            errors = exc.error_list if hasattr(exc, "error_list") else [exc]
            first_code = errors[0].code if errors else None
            api_code = self._PASSWORD_ERROR_CODE_MAP.get(first_code or "", "invalid_password")
            raise AccountServiceError(api_code, 400) from exc

    @staticmethod
    def normalize_email(email: str) -> str:
        """Normalize email for MVP uniqueness and lookup."""

        if not isinstance(email, str) or not email.strip():
            raise AccountServiceError(INVALID_REQUEST, 400)
        return email.strip().lower()

    def _required_google_credential(self, credential: str) -> str:
        """Validate the Google credential envelope before verification."""

        if not isinstance(credential, str) or not credential.strip():
            raise AccountServiceError(INVALID_REQUEST, 400)
        return credential.strip()

    def verify_google_credential(self, credential: str) -> dict[str, Any]:
        """Verify a Google ID token and return its canonical claims."""

        client_id = getattr(settings, "WISMO_GOOGLE_CLIENT_ID", "").strip()
        if not client_id:
            raise AccountServiceError("google_auth_not_configured", 503)

        try:
            payload = verify_oauth2_token(credential, GoogleAuthRequest(), audience=client_id)
        except (ValueError, GoogleAuthError) as exc:
            raise AccountServiceError("invalid_credentials", 401) from exc

        if not isinstance(payload, dict):
            raise AccountServiceError("invalid_credentials", 401)
        return payload

    def resolve_google_user(self, payload: dict[str, Any]) -> tuple[User, bool, bool]:
        """Resolve or create a registered user from verified Google claims."""

        google_id = str(payload.get("sub", "")).strip()
        email = self.normalize_email(str(payload.get("email", "")).strip())
        email_verified = payload.get("email_verified") is True
        if not google_id or not email or not email_verified:
            raise AccountServiceError("invalid_credentials", 401)

        user = User.objects.filter(google_id=google_id).first()
        if user is not None:
            return user, False, False

        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            if user.google_id and user.google_id != google_id:
                raise AccountServiceError("google_account_conflict", 409)
            user.google_id = google_id
            user.email_verified = True
            user.save(update_fields=["google_id", "email_verified"])
            return user, False, True

        user = User.objects.create_user(
            email=email,
            password=None,
            google_id=google_id,
            email_verified=True,
        )
        return user, True, False


class GuestAttachService:
    """Attach a guest-owned case to a verified registered user."""

    def attach_current_case(
        self,
        *,
        user: User,
        guest_identity: GuestIdentity,
        chat_id: str,
    ) -> AttachResult:
        """Transfer the current guest case to a registered user atomically."""

        if not user.is_active or not user.email_verified:
            raise AccountServiceError(SESSION_REQUIRED, 401)
        try:
            parsed_chat_id = uuid.UUID(str(chat_id))
        except ValueError as exc:
            raise AccountServiceError(INVALID_CHAT_ID, 400) from exc

        try:
            with transaction.atomic():
                chat = (
                    Chat.objects.select_for_update()
                    .filter(
                        id=parsed_chat_id,
                        guest_identity=guest_identity,
                        user__isnull=True,
                        is_archived=False,
                        disabled_at__isnull=True,
                    )
                    .first()
                )
                if chat is None:
                    raise AccountServiceError(GUEST_CHAT_NOT_FOUND, 404)

                case = None
                chats = Chat.objects.select_for_update().filter(id=chat.id)
                if chat.case_id is not None:
                    case = Case.objects.select_for_update().filter(
                        id=chat.case_id,
                        guest_identity=guest_identity,
                        user__isnull=True,
                    ).first()
                    if case is None:
                        raise AccountServiceError("attach_conflict", 409)
                    chats = Chat.objects.select_for_update().filter(
                        case=case,
                        guest_identity=guest_identity,
                        user__isnull=True,
                    )

                chat_ids = list(chats.values_list("id", flat=True))
                turns = ChatTurn.objects.select_for_update().filter(
                    chat_id__in=chat_ids,
                    guest_identity=guest_identity,
                    user__isnull=True,
                )
                turn_ids = list(turns.values_list("id", flat=True))

                if case is not None:
                    case.user = user
                    case.guest_identity = None
                    case.save(update_fields=["user", "guest_identity", "updated_at"])

                Chat.objects.filter(id__in=chat_ids).update(user=user, guest_identity=None)
                ChatTurn.objects.filter(id__in=turn_ids).update(user=user, guest_identity=None)

                ConsentService().require_reconsent(user=user)
                UsageQuotaWindow.current_for_identity(user=user)

                return AttachResult(
                    chat_id=chat.id,
                    case_id=case.id if case is not None else None,
                    transferred_chat_count=len(chat_ids),
                    transferred_turn_count=len(turn_ids),
                )
        except IntegrityError as exc:
            raise AccountServiceError("attach_conflict", 409) from exc


class AccountSettingsService:
    """Profile read, display_name update, password change, and GDPR data erasure for registered users."""

    def get_profile(self, user: User) -> dict:
        """Return the user's profile as a serializable dict."""

        return {
            "email": user.email,
            "display_name": user.display_name,
            "email_verified": user.email_verified,
            "date_joined": user.date_joined.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def update_display_name(self, user: User, display_name: str) -> dict:
        """Validate and persist a new display_name, returning the updated profile."""

        from wismo.contracts.codes import DISPLAY_NAME_TOO_LONG

        if not isinstance(display_name, str):
            raise AccountServiceError(INVALID_REQUEST, 400)
        if len(display_name) > 255:
            raise AccountServiceError(DISPLAY_NAME_TOO_LONG, 400)
        user.display_name = display_name
        user.save(update_fields=["display_name"])
        return self.get_profile(user)

    def change_password(self, request, user: User, current_password: str, new_password: str) -> None:
        """Verify current password then set a new one, keeping the session valid.

        Raises AccountServiceError for no usable password, wrong current password,
        or new password policy violations.
        """

        from django.contrib.auth import update_session_auth_hash

        from wismo.contracts.codes import INVALID_CURRENT_PASSWORD, NO_USABLE_PASSWORD

        if not user.has_usable_password():
            raise AccountServiceError(NO_USABLE_PASSWORD, 400)
        if not user.check_password(current_password):
            raise AccountServiceError(INVALID_CURRENT_PASSWORD, 400)
        try:
            validate_password(new_password, user=user)
        except ValidationError as exc:
            # Map the first Django validator code to our contract error codes.
            code = exc.error_list[0].code if exc.error_list else "invalid_password"
            raise AccountServiceError(code, 400) from exc
        user.set_password(new_password)
        user.save(update_fields=["password"])
        update_session_auth_hash(request, user)

    def add_password(self, user: User, new_password: str) -> None:
        """Set a password for a Google-only account that has no usable password.

        Raises AccountServiceError if the account already has a usable password
        (use change_password instead) or if new_password fails policy validation.
        """

        from wismo.contracts.codes import ALREADY_HAS_PASSWORD

        if user.has_usable_password():
            raise AccountServiceError(ALREADY_HAS_PASSWORD, 400)
        try:
            validate_password(new_password, user=user)
        except ValidationError as exc:
            code = exc.error_list[0].code if exc.error_list else "invalid_password"
            raise AccountServiceError(code, 400) from exc
        user.set_password(new_password)
        user.save(update_fields=["password"])

    def erase_all_chat_data(self, user: User) -> None:
        """Anonymize all chat history and profile data for a user (GDPR right to erasure).

        Ownership of cases, chats, turns, and memory items is transferred to the
        Anonymous Sentinel user. All personal content fields are cleared. The
        operation is atomic — either all tables are updated or none.
        """

        from accounts.constants import ANONYMOUS_USER_ID
        from memory.models import MemoryItem

        sentinel = User.objects.get(id=ANONYMOUS_USER_ID)

        with transaction.atomic():
            Case.objects.filter(user=user).update(
                user=sentinel,
                guest_identity=None,
                context_summary="",
                topic="",
            )
            Chat.objects.filter(user=user).update(
                user=sentinel,
                guest_identity=None,
                is_archived=True,
            )
            ChatTurn.objects.filter(user=user).update(
                user=sentinel,
                guest_identity=None,
                user_message_text="",
                assistant_response_text="",
            )
            MemoryItem.objects.filter(user=user).update(
                user=sentinel,
                case=None,
            )
