"""Unit tests for Main Flow Step 12 post-turn finalization."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from accounts.models import GuestIdentity
from chat.models import Case, Chat, ChatTurn
from chat.services import IdentityContext
from llm_ops.models import LLMUsageEvent
from memory.models import MemoryItem
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
            "explicit_profile_facts_next": [],
            "style_signals_next": [],
            "user_state_signals_next": [],
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
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: json.dumps({"action": "no_update"}),
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
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: json.dumps({"action": "no_update"}),
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
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: json.dumps({"action": "no_update"}),
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
        "explicit_profile_facts_next": ["works remotely", "works remotely"],
        "style_signals_next": ["prefers_brief_response", "prefers_brief_response"],
        "user_state_signals_next": ["overwhelmed", "ruminating"],
    }
    gateway = DummyGateway(
        responses={
            OperationKey.CONTEXT_SUMMARY_UPDATER.value: json.dumps({"has_meaningful_update": False}),
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: json.dumps({"action": "no_update"}),
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


def test_step12_long_term_memory_closes_old_segment_and_opens_new_active_segment() -> None:
    state = _create_state()
    old_segment = MemoryItem.objects.create(
        guest_identity=state.identity.guest_identity,
        case=state.case,
        segment_status="active",
        user_concern_summary="User started discussing work-related self-blame.",
        assistant_approach_summary="Assistant validated distress and reflected the pattern.",
        user_response_summary="User opened more about fear of judgment.",
        state_shift="From guarded to clearer disclosure.",
        open_loops=["Need practical step for current week."],
        confidence=0.8,
    )
    gateway = DummyGateway(
        responses={
            OperationKey.CONTEXT_SUMMARY_UPDATER.value: json.dumps({"has_meaningful_update": False}),
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: json.dumps(
                {
                    "action": "close_active_and_create_new_segment",
                    "closed_active_segment_update": {
                        "user_concern_summary": "User clarified shame after feedback is the core blocker.",
                        "assistant_approach_summary": "Assistant helped separate mistake from self-worth.",
                        "user_response_summary": "User felt relief and became more specific about goals.",
                        "state_shift": "From self-blame spiral to clearer target for change.",
                        "open_loops": ["Define first confidence-recovery action."],
                        "confidence": 0.86,
                    },
                    "new_segment_update": {
                        "user_concern_summary": "User wants a practical short-term plan to recover confidence this week.",
                        "assistant_approach_summary": "Assistant should move to structured action planning.",
                        "user_response_summary": "Pending next turn.",
                        "state_shift": "From reflection phase to planning phase.",
                        "open_loops": ["Pick one actionable step for tomorrow."],
                        "confidence": 0.84,
                    },
                }
            ),
        }
    )

    outcome = PostTurnFinalizationService(
        llm_gateway=gateway,
        quota_service=QuotaService(),
        state_store=IdentityStateStoreService(),
    ).run(state=state)

    old_segment.refresh_from_db()
    assert old_segment.segment_status == "closed"
    assert old_segment.end_turn_id == state.turn.id
    assert outcome.consolidation_meta["memory_items_upserted_count"] == 2
    new_active = (
        MemoryItem.objects.filter(
            case=state.case,
            guest_identity=state.identity.guest_identity,
            segment_status="active",
        )
        .exclude(id=old_segment.id)
        .first()
    )
    assert new_active is not None
    assert "practical short-term plan" in new_active.user_concern_summary
