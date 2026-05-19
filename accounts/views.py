"""Account, guest, OTP auth, and session API views."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.services import (
    GUEST_COOKIE_NAME,
    AccountAuthService,
    AccountServiceError,
    AccountSettingsService,
    GuestAttachService,
    IdentityService,
)
from runtime.services import RuntimeConfigService
from wismo.contracts.codes import INVALID_CHAT_ID, INVALID_REQUEST
from wismo.contracts.error import keyword_error_payload

logger = logging.getLogger(__name__)


def error_payload(error: AccountServiceError) -> dict[str, str]:
    """Serialize account service errors using the foundation error envelope."""

    return keyword_error_payload(error.code)


def required_string(data: dict[str, Any], field_name: str) -> str:
    """Read a required non-empty string field from request data."""

    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise AccountServiceError(INVALID_REQUEST, 400)
    return value.strip()


def optional_uuid(data: dict[str, Any], field_name: str) -> uuid.UUID | None:
    """Read an optional UUID field from request data."""

    if field_name not in data:
        return None
    value = data.get(field_name)
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise AccountServiceError(INVALID_CHAT_ID, 400) from exc


class GuestInitView(APIView):
    """Create a guest identity and set the guest cookie."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        """Create an ephemeral guest identity for immediate consent/chat."""

        service = IdentityService()
        guest = service.create_guest(request=request)
        payload = {
            "guest_token": str(guest.id),
            "session_state": "guest",
            "identity_type": "guest",
            "guest": service.guest_payload(guest),
            "consent_state": "required",
            "next_action": "accept_consent",
        }
        response = Response(payload, status=201)
        response.set_cookie(GUEST_COOKIE_NAME, str(guest.id), httponly=True, samesite="Lax")
        return response


class SessionStatusView(APIView):
    """Return canonical session and consent state for FE/BFF."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        """Resolve session state for the current request."""

        return Response(IdentityService().session_status(request=request), status=200)


class RegisterView(APIView):
    """Register an email/password account and send OTP verification."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        """Create or update an unverified account and issue an OTP."""

        try:
            result = AccountAuthService().register(
                email=required_string(request.data, "email"),
                password=required_string(request.data, "password"),
                display_name=str(request.data.get("display_name", "")).strip(),
            )
        except AccountServiceError as exc:
            return Response(error_payload(exc), status=exc.status_code)

        return Response(
            {
                "email": result.user.email,
                "email_verification_required": True,
                "otp_expires_at": result.otp_expires_at.isoformat(),
                "next_action": "verify_email",
            },
            status=201 if result.created else 200,
        )


class VerifyEmailView(APIView):
    """Verify account email with an OTP."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        """Mark the account verified when OTP is valid.

        If a guest cookie is present and the guest has an eligible active chat,
        silently attach that chat to the newly verified user. Attach failure does
        not block the verify response.
        """

        try:
            user = AccountAuthService().verify_email(
                email=required_string(request.data, "email"),
                otp=required_string(request.data, "otp"),
            )
        except AccountServiceError as exc:
            return Response(error_payload(exc), status=exc.status_code)

        response = Response(
            {
                "email": user.email,
                "email_verified": True,
                "next_action": "login",
            },
            status=200,
        )

        # Silent auto-attach: transfer guest chat if guest is present and eligible.
        identity_service = IdentityService()
        guest = identity_service.guest_from_request(request)
        if guest is not None and identity_service.is_guest_valid(guest):
            from chat.models import Chat

            eligible_chat = (
                Chat.objects.filter(
                    guest_identity=guest,
                    user__isnull=True,
                    is_archived=False,
                    disabled_at__isnull=True,
                )
                .order_by("-last_activity_at")
                .first()
            )
            if eligible_chat is not None:
                try:
                    GuestAttachService().attach_current_case(
                        user=user,
                        guest_identity=guest,
                        chat_id=str(eligible_chat.id),
                    )
                    response.delete_cookie(GUEST_COOKIE_NAME, samesite="Lax")
                except Exception:
                    logger.warning(
                        "Silent guest auto-attach failed after OTP verify for user %s guest %s",
                        user.id,
                        guest.id,
                        exc_info=True,
                    )

        return response


class ResendOtpView(APIView):
    """Resend OTP for an existing unverified account."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        """Issue a new OTP if cooldown and cap policy allow it."""

        try:
            result = AccountAuthService().resend_otp(
                email=required_string(request.data, "email"),
            )
        except AccountServiceError as exc:
            return Response(error_payload(exc), status=exc.status_code)

        return Response(
            {
                "email": result.user.email,
                "email_verification_required": True,
                "otp_expires_at": result.otp_expires_at.isoformat(),
                "next_action": "verify_email",
            },
            status=200,
        )


class LoginView(APIView):
    """Create a registered Django session for verified users."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        """Authenticate an email/password login request."""

        attach_chat_id: uuid.UUID | None = None
        try:
            attach_chat_id = optional_uuid(request.data, "attach_chat_id")
            AccountAuthService().login(
                request=request,
                email=required_string(request.data, "email"),
                password=required_string(request.data, "password"),
                attach_chat_id=attach_chat_id,
            )
        except AccountServiceError as exc:
            return Response(error_payload(exc), status=exc.status_code)
        response = Response(IdentityService().session_status(request=request), status=200)
        if attach_chat_id is not None:
            response.delete_cookie(GUEST_COOKIE_NAME, samesite="Lax")
        return response


class GoogleLoginView(APIView):
    """Create a registered Django session using a Google credential."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        """Verify a Google credential relayed by BFF and create session."""

        attach_chat_id: uuid.UUID | None = None
        try:
            attach_chat_id = optional_uuid(request.data, "attach_chat_id")
            AccountAuthService().login_with_google(
                request=request,
                credential=required_string(request.data, "credential"),
                attach_chat_id=attach_chat_id,
            )
        except AccountServiceError as exc:
            return Response(error_payload(exc), status=exc.status_code)
        response = Response(IdentityService().session_status(request=request), status=200)
        if attach_chat_id is not None:
            response.delete_cookie(GUEST_COOKIE_NAME, samesite="Lax")
        return response


class AccountMeView(APIView):
    """Read or update the authenticated registered user's profile."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return full profile for the current registered user."""

        return Response(AccountSettingsService().get_profile(request.user), status=200)

    def patch(self, request):
        """Update display_name for the current registered user."""

        display_name = request.data.get("display_name")
        if display_name is None or not isinstance(display_name, str):
            return Response(error_payload(AccountServiceError("invalid_request", 400)), status=400)
        try:
            profile = AccountSettingsService().update_display_name(request.user, display_name)
        except AccountServiceError as exc:
            return Response(error_payload(exc), status=exc.status_code)
        return Response(profile, status=200)


class ChangePasswordView(APIView):
    """Change password for the current registered user."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Verify current password and set a new one."""

        try:
            current_password = required_string(request.data, "current_password")
            new_password = required_string(request.data, "new_password")
        except AccountServiceError as exc:
            return Response(error_payload(exc), status=exc.status_code)
        try:
            AccountSettingsService().change_password(
                request=request,
                user=request.user,
                current_password=current_password,
                new_password=new_password,
            )
        except AccountServiceError as exc:
            return Response(error_payload(exc), status=exc.status_code)
        return Response({"password_changed": True}, status=200)


class AddPasswordView(APIView):
    """Set a password for a Google-only account that has no usable password."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Add a password to a Google-only account."""

        new_password = request.data.get("new_password")
        if not isinstance(new_password, str) or not new_password:
            return Response(error_payload(AccountServiceError(INVALID_REQUEST, 400)), status=400)
        try:
            AccountSettingsService().add_password(request.user, new_password)
        except AccountServiceError as exc:
            return Response(error_payload(exc), status=exc.status_code)
        return Response({"password_added": True}, status=200)


class DeleteAllChatView(APIView):
    """Anonymize all chat history and profile data (GDPR right to erasure)."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Erase all chat data for the current registered user."""

        AccountSettingsService().erase_all_chat_data(request.user)
        return Response({"erased": True}, status=200)


class LogoutView(APIView):
    """Clear the current registered Django session."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        """Log out and return the resulting session state."""

        AccountAuthService().logout(request=request)
        response = Response(IdentityService().session_status(request=request), status=200)
        response.delete_cookie(GUEST_COOKIE_NAME, samesite="Lax")
        return response


class ContactFormView(APIView):
    """Public contact form — sends submission to admin email configured in RuntimeConfig."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        """Validate fields and send contact form email to configured admin address."""

        data = request.data if isinstance(request.data, dict) else {}
        name = str(data.get("name", "")).strip()
        sender_email = str(data.get("email", "")).strip()
        subject = str(data.get("subject", "")).strip()
        message = str(data.get("message", "")).strip()

        errors: dict[str, str] = {}
        if not name:
            errors["name"] = "required"
        if not sender_email:
            errors["email"] = "required"
        else:
            try:
                validate_email(sender_email)
            except ValidationError:
                errors["email"] = "invalid"
        if not subject:
            errors["subject"] = "required"
        if not message:
            errors["message"] = "required"
        if errors:
            return Response({"error": "validation_error", "fields": errors}, status=400)

        admin_email = RuntimeConfigService().admin_contact_policy().email
        if not admin_email:
            logger.error("contact_form_no_admin_email: admin.contact_email not configured in RuntimeConfig")
            return Response({"error": "service_unavailable"}, status=503)

        body = f"Name: {name}\nEmail: {sender_email}\n\n{message}"
        try:
            send_mail(
                subject=f"[Contact] {subject}",
                message=body,
                from_email=None,  # uses DEFAULT_FROM_EMAIL from settings
                recipient_list=[admin_email],
                fail_silently=False,
            )
        except Exception:
            logger.exception("contact_form_send_failed sender=%s", sender_email)
            return Response({"error": "send_failed"}, status=502)

        return Response({"sent": True}, status=200)
