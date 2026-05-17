"""Request gate pipeline for MVP chat turns."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from django.utils import timezone

from accounts.services import AccountServiceError, IdentityService
from chat.models import Chat
from chat.services import IdentityContext
from consents.services import ConsentService
from runtime.models import UsageQuotaWindow
from runtime.services import QuotaService, RuntimeConfigService
from wismo.contracts.chat import ChatSendPayload
from wismo.contracts.codes import (
    CHAT_ACCESS_DENIED,
    CHAT_NOT_FOUND,
    CONSENT_REQUIRED,
    EMPTY_MESSAGE,
    GUEST_SESSION_EXPIRED,
    INVALID_CHAT_ID,
    INVALID_REQUEST,
    MESSAGE_TOO_LONG,
    MISSING_REQUIRED_FIELD,
    PAYLOAD_TOO_LARGE,
    QUOTA_EXCEEDED,
    REGISTRATION_REQUIRED_BY_QUOTA,
    TURN_IN_PROGRESS,
)
from wismo.contracts.enums import Step12FinalizationStatus


@dataclass
class GateResult:
    """Result of request gate processing."""

    passed: bool
    error_code: str | None = None
    status_code: int = 200
    payload: ChatSendPayload | None = None
    identity: IdentityContext | None = None
    quota_window: UsageQuotaWindow | None = None
    clear_guest_cookie: bool = False


class RequestGatePipeline:
    """Run the MVP request gate checks in canonical order."""

    def __init__(
        self,
        *,
        config_service: RuntimeConfigService | None = None,
        quota_service: QuotaService | None = None,
    ) -> None:
        """Create a gate pipeline with injectable runtime dependencies."""

        self.config_service = config_service or RuntimeConfigService()
        self.quota_service = quota_service or QuotaService(self.config_service)

    def run(self, *, request, data: dict) -> GateResult:
        """Validate and authorize a chat request before runtime core."""

        payload_result = self._validate_payload(data)
        if not payload_result.passed:
            return payload_result
        payload = payload_result.payload

        identity_result = self._resolve_identity(request)
        if not identity_result.passed:
            return identity_result
        identity = identity_result.identity

        session_result = self._check_session(identity)
        if not session_result.passed:
            session_result.clear_guest_cookie = identity_result.clear_guest_cookie
            return session_result

        # Refresh sliding TTL after session validity confirmed; applies even if
        # later gate steps (consent, quota) fail — sending a message counts as activity.
        if identity.guest_identity is not None:
            identity.guest_identity.mark_seen()

        consent_result = self._check_consent(identity)
        if not consent_result.passed:
            consent_result.clear_guest_cookie = identity_result.clear_guest_cookie
            return consent_result

        quota_window = self.quota_service.current_for_identity(**identity.owner_kwargs())
        quota_result = self._check_quota(identity, quota_window, payload.message)
        if not quota_result.passed:
            quota_result.clear_guest_cookie = identity_result.clear_guest_cookie
            return quota_result

        input_result = self._input_guard(
            request=request,
            payload=payload,
            data=data,
        )
        if not input_result.passed:
            input_result.clear_guest_cookie = identity_result.clear_guest_cookie
            return input_result

        ownership_result = self._check_chat_ownership(identity, payload.chat_id)
        if not ownership_result.passed:
            ownership_result.clear_guest_cookie = identity_result.clear_guest_cookie
            return ownership_result

        return GateResult(
            passed=True,
            payload=payload,
            identity=identity,
            quota_window=quota_window,
            clear_guest_cookie=identity_result.clear_guest_cookie,
        )

    def _validate_payload(self, data: dict) -> GateResult:
        """Validate payload shape and normalize chat request fields."""

        if not isinstance(data, dict):
            return GateResult(False, INVALID_REQUEST, 400)
        if "message" not in data:
            return GateResult(False, MISSING_REQUIRED_FIELD, 400)
        if not isinstance(data["message"], str):
            return GateResult(False, INVALID_REQUEST, 400)

        chat_id = None
        raw_chat_id = data.get("chat_id")
        if raw_chat_id not in (None, ""):
            try:
                chat_id = uuid.UUID(str(raw_chat_id))
            except ValueError:
                return GateResult(False, INVALID_CHAT_ID, 400)

        return GateResult(
            passed=True,
            payload=ChatSendPayload(
                message=data["message"],
                chat_id=chat_id,
            ),
        )

    def _resolve_identity(self, request) -> GateResult:
        """Resolve registered session identity or guest cookie/header identity."""

        identity_service = IdentityService()
        try:
            identity = identity_service.resolve_for_gate(request)
        except AccountServiceError as exc:
            return GateResult(False, exc.code, exc.status_code)

        return GateResult(
            passed=True,
            identity=identity,
            clear_guest_cookie=identity.is_user and identity_service.guest_token_from_request(request) is not None,
        )

    def _check_session(self, identity: IdentityContext) -> GateResult:
        """Check session validity for resolved identity.

        Registered users bypass this check — their session validity (is_active,
        email_verified) is already enforced by resolve_for_gate(), which raises
        SESSION_EXPIRED before returning an IdentityContext. Django session TTL
        expiry makes the user anonymous, caught upstream as IDENTITY_NOT_RESOLVED.
        """

        if identity.guest_identity is None:
            return GateResult(True)
        guest = identity.guest_identity
        if not guest.is_active:
            return GateResult(False, GUEST_SESSION_EXPIRED, 401)
        if guest.expires_at is not None and guest.expires_at <= timezone.now():
            return GateResult(False, GUEST_SESSION_EXPIRED, 401)
        return GateResult(True)

    def _check_consent(self, identity: IdentityContext) -> GateResult:
        """Check accepted consent before quota and input guard."""

        if ConsentService().has_active_consent(**identity.owner_kwargs()):
            return GateResult(True)
        return GateResult(False, CONSENT_REQUIRED, 403)

    def _check_quota(
        self,
        identity: IdentityContext,
        quota_window: UsageQuotaWindow,
        message: str,
    ) -> GateResult:
        """Stop runtime when identity quota is exhausted."""

        if not quota_window.is_exhausted:
            return GateResult(True)

        self.quota_service.append_pending_input(quota_window, message)
        if identity.is_user:
            return GateResult(False, QUOTA_EXCEEDED, 429)
        return GateResult(False, REGISTRATION_REQUIRED_BY_QUOTA, 429)

    def _input_guard(self, *, request, payload: ChatSendPayload, data: dict) -> GateResult:
        """Validate text-only input limits."""

        limits = self.config_service.input_limits()
        payload_size = self._payload_size_bytes(request=request, data=data)
        if payload_size > limits.max_payload_bytes:
            return GateResult(False, PAYLOAD_TOO_LARGE, 413)
        if not payload.message.strip():
            return GateResult(False, EMPTY_MESSAGE, 400)
        if len(payload.message) > limits.max_message_length_chars:
            return GateResult(False, MESSAGE_TOO_LONG, 413)
        return GateResult(True)

    @staticmethod
    def _payload_size_bytes(*, request, data: dict) -> int:
        """Return payload byte size using raw request body when available."""

        try:
            body = request.body  # type: ignore[attr-defined]
            if isinstance(body, (bytes, bytearray)):
                return len(body)
        except Exception:
            pass
        try:
            return len(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        except Exception:
            return len(str(data).encode("utf-8"))

    def _check_chat_ownership(self, identity: IdentityContext, chat_id) -> GateResult:
        """Validate existing chat ownership, bypassing new chat requests."""

        if chat_id is None:
            return GateResult(True)

        chat = Chat.objects.filter(id=chat_id).first()
        if chat is None or chat.is_archived or chat.disabled_at is not None:
            return GateResult(False, CHAT_NOT_FOUND, 404)

        if identity.user is not None and chat.user_id == identity.user.id:
            return self._check_previous_turn_barrier(chat)
        if identity.guest_identity is not None and chat.guest_identity_id == identity.guest_identity.id:
            return self._check_previous_turn_barrier(chat)
        return GateResult(False, CHAT_ACCESS_DENIED, 403)

    def _check_previous_turn_barrier(self, chat: Chat) -> GateResult:
        """Prevent normal runtime while the previous turn finalization is pending."""

        previous = chat.turns.order_by("-created_at").first()
        if previous is None:
            return GateResult(True)
        if previous.step12_finalization_status in {
            Step12FinalizationStatus.PENDING.value,
            Step12FinalizationStatus.PROCESSING.value,
        }:
            return GateResult(False, TURN_IN_PROGRESS, 409)
        return GateResult(True)
