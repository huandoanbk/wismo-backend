"""Unit tests for Step 5 case resolution service."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from accounts.models import GuestIdentity
from chat.models import Case, Chat, ChatTurn
from chat.services import CaseResolutionService, IdentityContext
from llm_ops.errors import LLM_GATEWAY_CONFIG_MISSING, LLMGatewayConfigurationError

pytestmark = pytest.mark.django_db


class FakeGateway:
    """Minimal fake gateway returning canned outputs per operation key."""

    def __init__(self, mapping: dict[str, str | Exception]) -> None:
        self.mapping = mapping

    def complete(self, *, operation_key, turn, prompt_messages):  # noqa: ANN001
        key = operation_key.value if hasattr(operation_key, "value") else str(operation_key)
        result = self.mapping[key]
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(text=result)


class CaptureGateway(FakeGateway):
    """Fake gateway that captures the latest prompt messages for assertions."""

    def __init__(self, mapping: dict[str, str | Exception]) -> None:
        super().__init__(mapping)
        self.last_prompt_messages: list[dict[str, str]] = []

    def complete(self, *, operation_key, turn, prompt_messages):  # noqa: ANN001
        self.last_prompt_messages = prompt_messages
        return super().complete(operation_key=operation_key, turn=turn, prompt_messages=prompt_messages)


def _create_identity_and_chat() -> tuple[IdentityContext, Chat, ChatTurn]:
    guest = GuestIdentity.objects.create()
    identity = IdentityContext(guest_identity=guest)
    chat = Chat.objects.create(guest_identity=guest, opening_input_text="opening")
    turn = ChatTurn.objects.create(
        guest_identity=guest,
        chat=chat,
        user_message_text="hello",
        status="processing",
    )
    return identity, chat, turn


def test_resolve_case_creates_new_case_when_identity_has_none() -> None:
    identity, chat, turn = _create_identity_and_chat()

    result = CaseResolutionService(llm_gateway=FakeGateway({})).resolve(
        identity=identity,
        chat=chat,
        message="new topic",
        turn=turn,
    )

    chat.refresh_from_db()
    assert result.status == "resolved"
    assert result.source == "new_case_first_identity_case"
    assert chat.case_id is not None


def test_resolve_case_uses_classifier_match_for_existing_cases() -> None:
    identity, chat, turn = _create_identity_and_chat()
    old_case = Case.objects.create(guest_identity=identity.guest_identity, topic="old", context_summary="a")
    Case.objects.create(guest_identity=identity.guest_identity, topic="new", context_summary="b")
    old_case.last_activity_at = old_case.last_activity_at.replace(year=2020)
    old_case.save(update_fields=["last_activity_at"])

    service = CaseResolutionService(
        llm_gateway=FakeGateway(
            {"case_classifier": f'{{"decision":"matched_existing_case","matched_case_id":"{old_case.id}"}}'}
        ),
    )
    result = service.resolve(identity=identity, chat=chat, message="same issue", turn=turn)

    chat.refresh_from_db()
    assert result.status == "resolved"
    assert result.source == "case_classifier_match"
    assert chat.case_id == old_case.id


def test_case_classifier_uses_current_turn_message_not_opening_text() -> None:
    identity, chat, turn = _create_identity_and_chat()
    Case.objects.create(guest_identity=identity.guest_identity, topic="old", context_summary="a")
    gateway = CaptureGateway({"case_classifier": '{"decision":"ambiguous"}'})

    CaseResolutionService(llm_gateway=gateway).resolve(
        identity=identity,
        chat=chat,
        message="follow-up message",
        turn=turn,
    )

    assert len(gateway.last_prompt_messages) == 2
    payload = json.loads(gateway.last_prompt_messages[1]["content"])
    assert payload["current_message"] == "follow-up message"
    assert payload["current_message"] != chat.opening_input_text


def test_classifier_match_falls_back_to_recency_when_matched_case_id_invalid() -> None:
    identity, chat, turn = _create_identity_and_chat()
    Case.objects.create(guest_identity=identity.guest_identity, topic="old", context_summary="a")
    new_case = Case.objects.create(guest_identity=identity.guest_identity, topic="new", context_summary="b")

    service = CaseResolutionService(
        llm_gateway=FakeGateway(
            {"case_classifier": '{"decision":"matched_existing_case","matched_case_id":"not-a-real-id"}'}
        ),
    )
    result = service.resolve(identity=identity, chat=chat, message="same issue", turn=turn)

    chat.refresh_from_db()
    assert result.status == "resolved"
    assert result.source == "case_classifier_match"
    assert chat.case_id == new_case.id


def test_resolve_case_ambiguous_sets_pending_and_keeps_null_case() -> None:
    identity, chat, turn = _create_identity_and_chat()
    Case.objects.create(guest_identity=identity.guest_identity, topic="old", context_summary="a")

    service = CaseResolutionService(
        llm_gateway=FakeGateway({"case_classifier": '{"decision":"ambiguous"}'}),
    )
    result = service.resolve(identity=identity, chat=chat, message="unclear", turn=turn)

    chat.refresh_from_db()
    assert result.status == "pending_confirmation"
    assert chat.case_id is None
    assert chat.is_pending_case_confirmation is True
    assert chat.pending_confirm_turn_count == 0


def test_pending_classifier_auto_creates_case_after_third_ambiguous_turn() -> None:
    identity, chat, turn = _create_identity_and_chat()
    chat.is_pending_case_confirmation = True
    chat.pending_confirm_turn_count = 2
    chat.save(update_fields=["is_pending_case_confirmation", "pending_confirm_turn_count"])
    Case.objects.create(guest_identity=identity.guest_identity, topic="old", context_summary="a")

    service = CaseResolutionService(
        llm_gateway=FakeGateway({"case_classifier": '{"decision":"ambiguous"}'}),
    )
    result = service.resolve(identity=identity, chat=chat, message="still unclear", turn=turn)

    chat.refresh_from_db()
    assert result.status == "resolved"
    assert result.source == "pending_auto_resolve"
    assert chat.case_id is not None
    assert chat.is_pending_case_confirmation is False
    assert chat.pending_confirm_turn_count == 0


def test_classifier_unavailable_keeps_case_null() -> None:
    identity, chat, turn = _create_identity_and_chat()
    Case.objects.create(guest_identity=identity.guest_identity, topic="old", context_summary="a")

    service = CaseResolutionService(
        llm_gateway=FakeGateway({"case_classifier": LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_MISSING)}),
    )
    result = service.resolve(identity=identity, chat=chat, message="same issue", turn=turn)

    chat.refresh_from_db()
    assert result.status == "classifier_unavailable"
    assert chat.case_id is None
    assert chat.is_pending_case_confirmation is True


def test_existing_chat_case_auto_clears_stale_pending_flags() -> None:
    identity, chat, turn = _create_identity_and_chat()
    case = Case.objects.create(guest_identity=identity.guest_identity, topic="old", context_summary="a")
    chat.case = case
    chat.is_pending_case_confirmation = True
    chat.pending_confirm_turn_count = 2
    chat.save(update_fields=["case", "is_pending_case_confirmation", "pending_confirm_turn_count"])

    result = CaseResolutionService(llm_gateway=FakeGateway({})).resolve(
        identity=identity,
        chat=chat,
        message="same issue",
        turn=turn,
    )

    chat.refresh_from_db()
    assert result.status == "resolved"
    assert result.source == "existing_chat"
    assert chat.is_pending_case_confirmation is False
    assert chat.pending_confirm_turn_count == 0
