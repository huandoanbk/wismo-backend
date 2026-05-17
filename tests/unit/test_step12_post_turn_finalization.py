"""Unit tests for Main Flow Step 12 post-turn finalization."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from accounts.models import GuestIdentity
from chat.models import Case, Chat, ChatTurn
from chat.services import IdentityContext
from llm_ops.models import LLMUsageEvent
from runtime.finalization import PostTurnFinalizationService
from runtime.models import UsageQuotaWindow
from runtime.services import IdentityStateStoreService, QuotaService
from wismo.contracts.enums import (
    OperationKey,
    ResponseMethod,
    Step12FinalizationStatus,
    UsageAccountingStatus,
)

pytestmark = pytest.mark.django_db


class DummyGateway:
    """Simple gateway stub returning canned JSON payloads by operation key."""

    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses

    def complete(self, *, operation_key, turn, prompt_messages):  # noqa: ANN001
        _ = turn, prompt_messages
        key = operation_key.value if hasattr(operation_key, "value") else str(operation_key)
        return SimpleNamespace(text=self.responses[key])


def _create_state() -> SimpleNamespace:
    guest = GuestIdentity.objects.create()
    identity = IdentityContext(guest_identity=guest)
    case = Case.objects.create(guest_identity=guest, topic="conflict", context_summary="old summary")
    chat = Chat.objects.create(guest_identity=guest, case=case)
    turn = ChatTurn.objects.create(
        guest_identity=guest,
        chat=chat,
        case=case,
        user_message_text="current message",
        assistant_response_text="assistant response",
        response_method=ResponseMethod.ASK.value,
        status="completed",
    )
    quota_window = UsageQuotaWindow.objects.create(guest_identity=guest, token_limit=20, used_tokens=0)
    return SimpleNamespace(
        identity=identity,
        case=case,
        chat=chat,
        turn=turn,
        quota_window=quota_window,
        response_text="assistant response",
        runtime_bundle={
            "context_summary": "old summary",
            "long_term_memory": [],
        },
        normalized_reasoning_result={
            "intent": "ask_how_to_respond",
            "case_slots": {"core_problem": "conflict"},
            "explicit_profile_facts": [],
            "style_signals": [],
            "user_state_signals": [],
        },
    )


def _add_usage_event(*, turn: ChatTurn, operation_key: str, input_tokens: int, output_tokens: int) -> None:
    LLMUsageEvent.objects.create(
        turn=turn,
        operation_key=operation_key,
        supplier_name="stub",
        model_name="model",
        input_tokens=input_tokens,
        cached_input_tokens=0,
        output_tokens=output_tokens,
        cache_write_tokens=0,
        latency_ms=1,
        status="success",
        error_code="",
    )


def test_step12_usage_and_quota_success_path() -> None:
    state = _create_state()
    _add_usage_event(turn=state.turn, operation_key=OperationKey.FULL_REASONING.value, input_tokens=3, output_tokens=2)
    _add_usage_event(
        turn=state.turn,
        operation_key=OperationKey.RESPONSE_GENERATION.value,
        input_tokens=4,
        output_tokens=1,
    )
    gateway = DummyGateway(
        responses={
            OperationKey.CONTEXT_SUMMARY_UPDATER.value: json.dumps(
                {"has_meaningful_update": True, "new_context_summary_text": "new summary"}
            ),
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: json.dumps({"candidate_memory_items": []}),
        }
    )
    outcome = PostTurnFinalizationService(
        llm_gateway=gateway,
        quota_service=QuotaService(),
        state_store=IdentityStateStoreService(),
    ).run(state=state)

    state.turn.refresh_from_db()
    state.quota_window.refresh_from_db()
    assert state.turn.total_billable_tokens == 10
    assert state.turn.usage_accounting_status == UsageAccountingStatus.FINALIZED.value
    assert state.turn.step12_finalization_status == Step12FinalizationStatus.FINALIZED.value
    assert state.turn.quota_exhausted_after_turn is False
    assert state.turn.quota_window_after["used_tokens"] == 0
    assert outcome.step12_finalization_status == Step12FinalizationStatus.FINALIZED.value
    assert state.case.context_summary == "new summary"


def test_step12_marks_partial_when_consolidation_subtask_fails() -> None:
    state = _create_state()
    _add_usage_event(turn=state.turn, operation_key=OperationKey.FULL_REASONING.value, input_tokens=5, output_tokens=1)
    gateway = DummyGateway(
        responses={
            OperationKey.CONTEXT_SUMMARY_UPDATER.value: "{bad-json",
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: json.dumps({"candidate_memory_items": []}),
        }
    )
    outcome = PostTurnFinalizationService(
        llm_gateway=gateway,
        quota_service=QuotaService(),
        state_store=IdentityStateStoreService(),
    ).run(state=state)

    state.turn.refresh_from_db()
    assert outcome.step12_finalization_status == Step12FinalizationStatus.PARTIAL.value
    assert state.turn.step12_finalization_status == Step12FinalizationStatus.PARTIAL.value
    assert state.turn.usage_accounting_status == UsageAccountingStatus.FINALIZED.value


def test_step12_memory_extractor_fallback_keeps_turn_alive() -> None:
    state = _create_state()
    _add_usage_event(turn=state.turn, operation_key=OperationKey.FULL_REASONING.value, input_tokens=5, output_tokens=1)
    gateway = DummyGateway(
        responses={
            OperationKey.CONTEXT_SUMMARY_UPDATER.value: json.dumps({"has_meaningful_update": False}),
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: "{invalid",
        }
    )
    outcome = PostTurnFinalizationService(
        llm_gateway=gateway,
        quota_service=QuotaService(),
        state_store=IdentityStateStoreService(),
    ).run(state=state)

    assert outcome.step12_finalization_status == Step12FinalizationStatus.PARTIAL.value
    assert outcome.consolidation_meta["memory_items_upserted_count"] == 0


def test_step12_ignores_quota_consume_override_under_realtime_usage_mode() -> None:
    state = _create_state()
    gateway = DummyGateway(
        responses={
            OperationKey.CONTEXT_SUMMARY_UPDATER.value: json.dumps({"has_meaningful_update": False}),
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: json.dumps({"candidate_memory_items": []}),
        }
    )

    outcome = PostTurnFinalizationService(
        llm_gateway=gateway,
        quota_service=QuotaService(),
        state_store=IdentityStateStoreService(),
    ).run(state=state)

    state.turn.refresh_from_db()
    assert outcome.usage_accounting_status == UsageAccountingStatus.FINALIZED.value
    assert outcome.step12_finalization_status == Step12FinalizationStatus.FINALIZED.value
    assert state.turn.step12_finalization_status == Step12FinalizationStatus.FINALIZED.value


def test_step12_rule_based_updates_persist_identity_state() -> None:
    state = _create_state()
    _add_usage_event(turn=state.turn, operation_key=OperationKey.FULL_REASONING.value, input_tokens=2, output_tokens=2)
    state.normalized_reasoning_result = {
        "intent": "self_understanding",
        "case_slots": {"core_problem": "stress"},
        "explicit_profile_facts": ["works remotely", "works remotely"],
        "style_signals": ["prefers_brief_response", "prefers_brief_response"],
        "user_state_signals": ["overwhelmed", "ruminating"],
    }
    gateway = DummyGateway(
        responses={
            OperationKey.CONTEXT_SUMMARY_UPDATER.value: json.dumps({"has_meaningful_update": False}),
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: json.dumps({"candidate_memory_items": []}),
        }
    )
    service = PostTurnFinalizationService(
        llm_gateway=gateway,
        quota_service=QuotaService(),
        state_store=IdentityStateStoreService(),
    )
    service.run(state=state)
    service.run(state=state)

    profile, preference, snapshot = IdentityStateStoreService().read_bundle_fields(identity=state.identity)
    assert profile["facts"] == ["works remotely"]
    assert preference.get("prefers_brief_response") is True
    assert snapshot.get("primary_state") == "overwhelmed"
