"""Chat persistence helpers for the MVP runtime and bootstrap APIs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from django.db.models.query import QuerySet
from django.utils import timezone

from accounts.models import GuestIdentity, User
from chat.models import Case, Chat, ChatTurn
from llm_ops.errors import LLM_GATEWAY_CONFIG_INVALID, LLM_GATEWAY_CONFIG_MISSING, LLMGatewayError
from llm_ops.gateway import LLMGateway
from runtime.prompts import CASE_CLASSIFIER_SYSTEM
from wismo.contracts.codes import (
    CHAT_ACCESS_DENIED,
    CHAT_NOT_FOUND,
    GUEST_SESSION_EXPIRED,
    IDENTITY_NOT_RESOLVED,
    SESSION_EXPIRED,
    TURN_IN_PROGRESS,
)
from wismo.contracts.enums import OperationKey

CHAT_DISPLAY_NAME_FALLBACK = "Cuộc trò chuyện mới"


class ChatBootstrapError(Exception):
    """Domain error surfaced by chat bootstrap API views."""

    def __init__(self, code: str, status_code: int = 400) -> None:
        """Create a chat bootstrap error with API status metadata."""

        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class IdentityContext:
    """Resolved owner identity for runtime and persistence."""

    user: User | None = None
    guest_identity: GuestIdentity | None = None

    @property
    def is_user(self) -> bool:
        """Return whether this identity is a registered user."""

        return self.user is not None

    def owner_kwargs(self) -> dict:
        """Return ORM owner kwargs for models using user/guest fields."""

        if self.user is not None:
            return {"user": self.user, "guest_identity": None}
        if self.guest_identity is not None:
            return {"user": None, "guest_identity": self.guest_identity}
        raise ValueError("IdentityContext has no owner.")


class ChatContextService:
    """Create and load chat/case context for runtime steps."""

    def resolve_bootstrap_identity(self, *, request: Any) -> IdentityContext:
        """Resolve a valid identity for chat bootstrap endpoints."""

        from accounts.services import IdentityService

        identity_service = IdentityService()
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            if user.is_active and user.email_verified:
                user.last_seen_at = timezone.now()
                user.save(update_fields=["last_seen_at"])
                return IdentityContext(user=user)
            raise ChatBootstrapError(SESSION_EXPIRED, 401)

        guest = identity_service.guest_from_request(request)
        if guest is None:
            raise ChatBootstrapError(IDENTITY_NOT_RESOLVED, 401)
        if not identity_service.is_guest_valid(guest):
            raise ChatBootstrapError(GUEST_SESSION_EXPIRED, 401)

        return IdentityContext(guest_identity=guest)

    def create_chat(self, *, identity: IdentityContext, opening_input_text: str = "") -> Chat:
        """Create a new chat shell for the resolved owner identity."""

        return Chat.objects.create(
            **identity.owner_kwargs(),
            chat_display_name=CHAT_DISPLAY_NAME_FALLBACK,
            opening_input_text=opening_input_text,
            last_activity_at=timezone.now(),
        )

    def list_chats(self, *, identity: IdentityContext) -> QuerySet[Chat]:
        """Return chats owned by the resolved identity in recency order."""

        return (
            Chat.objects.filter(
                **identity.owner_kwargs(),
                is_archived=False,
                disabled_at__isnull=True,
            )
            .order_by("-last_activity_at", "-created_at", "-id")
        )

    def get_owned_chat(self, *, identity: IdentityContext, chat_id: Any) -> Chat:
        """Return a chat owned by the resolved identity or raise a public error."""

        chat = Chat.objects.filter(id=chat_id).first()
        if chat is None or chat.is_archived or chat.disabled_at is not None:
            raise ChatBootstrapError(CHAT_NOT_FOUND, 404)

        if chat.user_id is not None:
            if identity.user is not None and chat.user_id == identity.user.id:
                return chat
            raise ChatBootstrapError(CHAT_ACCESS_DENIED, 403)

        if chat.guest_identity_id is not None:
            if (
                identity.guest_identity is not None
                and chat.guest_identity_id == identity.guest_identity.id
            ):
                return chat
            raise ChatBootstrapError(CHAT_ACCESS_DENIED, 403)

        raise ChatBootstrapError(CHAT_NOT_FOUND, 404)

    def archive_chat(self, *, identity: IdentityContext, chat_id: Any) -> None:
        """Archive a chat owned by the resolved identity.

        Raises ChatBootstrapError if the chat is not found, not owned, or has a turn in progress.
        """

        chat = self.get_owned_chat(identity=identity, chat_id=chat_id)
        if chat.turns.filter(status="processing").exists():
            raise ChatBootstrapError(TURN_IN_PROGRESS, 409)
        chat.is_archived = True
        chat.save(update_fields=["is_archived"])

    def _canonical_chat_display_name(self, chat: Chat) -> str:
        """Return the canonical display name exposed to FE/BFF."""

        display_name = (chat.chat_display_name or "").strip()
        if not display_name or display_name == "New chat":
            return CHAT_DISPLAY_NAME_FALLBACK
        return display_name

    def chat_summary_payload(self, chat: Chat) -> dict[str, Any]:
        """Serialize chat metadata used by list/detail/bootstrap responses."""

        return {
            "chat_id": str(chat.id),
            "chat_display_name": self._canonical_chat_display_name(chat),
            "case_id": str(chat.case_id) if chat.case_id is not None else None,
            "opening_input_text": chat.opening_input_text,
            "created_at": chat.created_at.isoformat() if chat.created_at else None,
            "last_activity_at": chat.last_activity_at.isoformat()
            if chat.last_activity_at
            else None,
        }

    def turn_payload(self, turn: ChatTurn) -> dict[str, Any]:
        """Serialize one chat turn for detail history responses."""

        return {
            "turn_id": str(turn.id),
            "user_message_text": turn.user_message_text,
            "assistant_response_text": turn.assistant_response_text,
            "response_method": turn.response_method,
            "status": turn.status,
            "created_at": turn.created_at.isoformat() if turn.created_at else None,
            "finalized_at": turn.finalized_at.isoformat() if turn.finalized_at else None,
            "case_id": str(turn.case_id) if turn.case_id is not None else None,
        }

    def chat_detail_payload(self, chat: Chat) -> dict[str, Any]:
        """Serialize a chat with its turn history ordered chronologically."""

        turns = list(chat.turns.order_by("created_at", "id"))
        return {
            "chat": self.chat_summary_payload(chat),
            "turns": [self.turn_payload(turn) for turn in turns],
        }

    def chat_list_payload(self, *, identity: IdentityContext) -> dict[str, Any]:
        """Serialize the chat list for the resolved identity."""

        chats = self.list_chats(identity=identity)
        return {"chats": [self.chat_summary_payload(chat) for chat in chats]}

    def resolve_chat(self, *, identity: IdentityContext, chat_id: Any, message: str) -> Chat:
        """Load an existing chat or create a new chat for the identity."""

        if chat_id is not None:
            filters = {"id": chat_id, "is_archived": False, "disabled_at__isnull": True}
            filters.update(identity.owner_kwargs())
            chat = Chat.objects.filter(**filters).first()
            if chat is None:
                raise Chat.DoesNotExist
            return chat

        return self.create_chat(identity=identity, opening_input_text=message)

    def resolve_case(
        self,
        *,
        identity: IdentityContext,
        chat: Chat,
        message: str,
        turn: ChatTurn,
        llm_gateway: LLMGateway | None = None,
    ) -> CaseResolutionResult:
        """Resolve Step 5 case context for one turn."""

        return CaseResolutionService(llm_gateway=llm_gateway).resolve(
            identity=identity,
            chat=chat,
            message=message,
            turn=turn,
        )


@dataclass(frozen=True)
class CaseResolutionResult:
    """Result of Step 5 case resolution."""

    case: Case | None
    status: str
    source: str
    detail: str = ""


class CaseResolutionService:
    """Resolve runtime Step 5 case context for a chat turn."""

    def __init__(self, *, llm_gateway: LLMGateway | None = None) -> None:
        """Create a resolver with injectable LLM gateway."""

        self.llm_gateway = llm_gateway or LLMGateway()

    def resolve(
        self,
        *,
        identity: IdentityContext,
        chat: Chat,
        message: str,
        turn: ChatTurn,
    ) -> CaseResolutionResult:
        """Resolve one case for current turn using Main Flow Step 5 branches."""

        if chat.case_id is not None:
            if chat.is_pending_case_confirmation or chat.pending_confirm_turn_count != 0:
                self._clear_pending(chat=chat)
            return CaseResolutionResult(case=chat.case, status="resolved", source="existing_chat")

        if chat.is_pending_case_confirmation:
            return self._resolve_pending(identity=identity, chat=chat, message=message, turn=turn)

        cases = list(
            Case.objects.filter(**identity.owner_kwargs())
            .order_by("-last_activity_at", "-created_at", "-id")
        )
        if not cases:
            case = self._create_case(identity=identity, message=message)
            self._attach_case(chat=chat, case=case)
            return CaseResolutionResult(case=case, status="resolved", source="new_case_first_identity_case")

        result = self._run_case_classifier(chat=chat, message=message, turn=turn, cases=cases)
        if result is not None and result.decision == "matched_existing_case":
            case = self._pick_case_by_id(cases=cases, matched_case_id=result.matched_case_id)
            self._attach_case(chat=chat, case=case)
            return CaseResolutionResult(case=case, status="resolved", source="case_classifier_match")
        if result is not None and result.decision == "new_case":
            case = self._create_case(identity=identity, message=message)
            self._attach_case(chat=chat, case=case)
            return CaseResolutionResult(case=case, status="resolved", source="case_classifier_new")

        # ambiguous or classifier unavailable on first encounter — enter pending state
        self._set_pending(chat=chat, count=0)
        if result is None:
            return CaseResolutionResult(case=None, status="classifier_unavailable", source="case_classifier_unavailable")
        return CaseResolutionResult(case=None, status="pending_confirmation", source="case_classifier_ambiguous")

    def _resolve_pending(
        self,
        *,
        identity: IdentityContext,
        chat: Chat,
        message: str,
        turn: ChatTurn,
    ) -> CaseResolutionResult:
        """Resolve pending case confirmation using the shared case classifier."""

        cases = list(
            Case.objects.filter(**identity.owner_kwargs())
            .order_by("-last_activity_at", "-created_at", "-id")
        )
        result = self._run_case_classifier(chat=chat, message=message, turn=turn, cases=cases)
        if result is not None and result.decision == "matched_existing_case":
            case = self._pick_case_by_id(cases=cases, matched_case_id=result.matched_case_id)
            self._attach_case(chat=chat, case=case)
            self._clear_pending(chat=chat)
            return CaseResolutionResult(case=case, status="resolved", source="case_classifier_match")
        if result is not None and result.decision == "new_case":
            case = self._create_case(identity=identity, message=message)
            self._attach_case(chat=chat, case=case)
            self._clear_pending(chat=chat)
            return CaseResolutionResult(case=case, status="resolved", source="case_classifier_new")

        # ambiguous or classifier unavailable — advance pending counter
        next_count = min(chat.pending_confirm_turn_count + 1, 255)
        if next_count >= 3:
            case = self._create_case(identity=identity, message=message)
            self._attach_case(chat=chat, case=case)
            self._clear_pending(chat=chat)
            return CaseResolutionResult(case=case, status="resolved", source="pending_auto_resolve")
        self._set_pending(chat=chat, count=next_count)
        if result is None:
            return CaseResolutionResult(case=None, status="classifier_unavailable", source="case_classifier_unavailable")
        return CaseResolutionResult(case=None, status="pending_confirmation", source="case_classifier_ambiguous")

    def _run_case_classifier(
        self, *, chat: Chat, message: str, turn: ChatTurn, cases: list[Case]
    ) -> CaseDetectorDecision | None:
        """Call the unified case classifier for both initial and pending resolution flows.

        Input: current message + recent case summaries.
        Output: matched_existing_case (with case_id) / new_case / ambiguous.
        """

        summaries = self._recent_case_summaries(cases)
        prompt_messages = [
            {
                "role": "system",
                "content": CASE_CLASSIFIER_SYSTEM,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "current_message": message,
                        "recent_case_summaries": summaries,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            completion = self.llm_gateway.complete(
                operation_key=OperationKey.CASE_CLASSIFIER,
                turn=turn,
                prompt_messages=prompt_messages,
            )
        except LLMGatewayError as exc:
            if exc.code not in {LLM_GATEWAY_CONFIG_MISSING, LLM_GATEWAY_CONFIG_INVALID}:
                raise
            return None
        return self._parse_classifier_decision(completion.text)

    @staticmethod
    def _parse_classifier_decision(raw_text: str) -> CaseDetectorDecision | None:
        """Parse and normalize unified case classifier output."""

        canonical = {"matched_existing_case", "new_case", "ambiguous"}
        stripped = raw_text.strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                decision = str(parsed.get("decision", "")).strip()
                if decision in canonical:
                    matched_case_id = str(parsed.get("matched_case_id", "")).strip() or None
                    return CaseDetectorDecision(decision=decision, matched_case_id=matched_case_id)
        except json.JSONDecodeError:
            pass
        if stripped in canonical:
            return CaseDetectorDecision(decision=stripped, matched_case_id=None)
        for decision in canonical:
            if decision in stripped:
                return CaseDetectorDecision(decision=decision, matched_case_id=None)
        return None

    @staticmethod
    def _pick_case_by_id(*, cases: list[Case], matched_case_id: str | None) -> Case:
        """Resolve classifier-selected case id; fallback to recency when id is missing/invalid."""

        if matched_case_id is not None:
            for case in cases:
                if str(case.id) == matched_case_id:
                    return case
        return cases[0]

    @staticmethod
    def _recent_case_summaries(cases: list[Case]) -> list[dict[str, str]]:
        """Serialize max 10 recent case summaries in recency order."""

        summaries: list[dict[str, str]] = []
        for case in cases[:10]:
            summaries.append(
                {
                    "case_id": str(case.id),
                    "context_summary": case.context_summary,
                }
            )
        return summaries

    @staticmethod
    def _set_pending(*, chat: Chat, count: int) -> None:
        """Set pending confirmation state with explicit counter."""

        chat.is_pending_case_confirmation = True
        chat.pending_confirm_turn_count = count
        chat.save(update_fields=["is_pending_case_confirmation", "pending_confirm_turn_count", "updated_at"])

    @staticmethod
    def _clear_pending(*, chat: Chat) -> None:
        """Clear pending confirmation state after case is resolved."""

        chat.is_pending_case_confirmation = False
        chat.pending_confirm_turn_count = 0
        chat.save(update_fields=["is_pending_case_confirmation", "pending_confirm_turn_count", "updated_at"])

    @staticmethod
    def _attach_case(*, chat: Chat, case: Case) -> None:
        """Attach a resolved case to chat."""

        chat.case = case
        chat.save(update_fields=["case", "updated_at"])

    @staticmethod
    def _create_case(*, identity: IdentityContext, message: str) -> Case:
        """Create a new case for the current identity."""

        return Case.objects.create(
            **identity.owner_kwargs(),
            topic=message.strip()[:120],
            context_summary="",
            last_activity_at=timezone.now(),
        )


@dataclass(frozen=True)
class CaseDetectorDecision:
    """Normalized result of the unified case classifier."""

    decision: str
    matched_case_id: str | None
