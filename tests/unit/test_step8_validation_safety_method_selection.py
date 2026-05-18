"""Unit tests for Main Flow Step 8 validation/safety/method selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from accounts.models import GuestIdentity
from chat.models import Chat, ChatTurn
from chat.services import IdentityContext
from runtime.orchestrator import RuntimeOrchestrator, RuntimeState
from runtime.services import IdentityStateStoreService
from wismo.contracts.enums import ResponseMethod

pytestmark = pytest.mark.django_db


def _state_with_reasoning(reasoning_result: dict) -> RuntimeState:
    guest = GuestIdentity.objects.create()
    identity = IdentityContext(guest_identity=guest)
    chat = Chat.objects.create(guest_identity=guest, opening_input_text="open")
    turn = ChatTurn.objects.create(guest_identity=guest, chat=chat, user_message_text="m")
    return RuntimeState(
        request_payload=SimpleNamespace(message="hello"),
        identity=identity,
        quota_window=SimpleNamespace(),
        chat=chat,
        case=None,
        turn=turn,
        runtime_bundle={
            "current_message": "hello",
            "recent_turns": [],
            "context_summary": "",
            "user_profile": {},
            "user_preference": {},
            "user_state": {},
            "long_term_memory": [],
        },
        reasoning_result=reasoning_result,
    )


def _base_reasoning(**overrides):
    data = {
        "intent": "unclear",
        "action_recommended": "ASK",
        "required_next_slots": ["core_problem"],
        "case_slots": {
            "core_problem": "",
            "who_involved": "",
            "trigger": "",
            "timeframe": "",
            "prior_attempt": "",
            "goal": "",
            "desired_outcome": "",
        },
        "turn_strategy": {"focus": "", "angle": "", "avoid": []},
        "explicit_profile_facts_next": [],
        "style_signals_next": ["none"],
        "user_state_signals_next": ["none"],
        "suggested_chat_display_name": None,
    }
    data.update(overrides)
    return data


def test_step8_does_not_apply_hard_safety_override_from_reasoning_payload() -> None:
    state = _state_with_reasoning(_base_reasoning(action_recommended="LISTEN"))

    RuntimeOrchestrator()._validate_and_select_response_method(state)

    assert state.response_method == ResponseMethod.LISTEN
    assert state.retrieval_required is False


def test_step8_sets_retrieval_required_only_for_teach() -> None:
    teach_state = _state_with_reasoning(
        _base_reasoning(
            intent="ask_teaching_or_perspective",
            action_recommended="TEACH",
            required_next_slots=[],
            case_slots={
                "core_problem": "x",
                "who_involved": "y",
                "trigger": "z",
                "timeframe": "",
                "prior_attempt": "",
                "goal": "",
                "desired_outcome": "",
            },
        )
    )
    ask_state = _state_with_reasoning(_base_reasoning())

    orchestrator = RuntimeOrchestrator()
    orchestrator._validate_and_select_response_method(teach_state)
    orchestrator._validate_and_select_response_method(ask_state)

    assert teach_state.response_method == ResponseMethod.TEACH
    assert teach_state.retrieval_required is True
    assert ask_state.retrieval_required is False


def test_step8_corrective_retry_then_success() -> None:
    # Trigger: missing required fields fires schema_heavy corrective retry.
    state = _state_with_reasoning({"intent": "unclear"})
    orchestrator = RuntimeOrchestrator()

    def _fake_full_reasoning(inner_state: RuntimeState) -> None:
        inner_state.reasoning_result = _base_reasoning(
            action_recommended="ASK",
            required_next_slots=["core_problem"],
        )

    orchestrator._full_reasoning = _fake_full_reasoning  # type: ignore[assignment]

    orchestrator._validate_and_select_response_method(state)

    assert state.reasoning_corrective_retry_count == 1
    assert state.response_method == ResponseMethod.ASK
    assert state.normalized_reasoning_result["required_next_slots"] == ["core_problem"]


def test_step8_corrective_retry_exhausted_falls_back_to_safe_ask() -> None:
    # Trigger: missing required fields; fake keeps returning incomplete response.
    state = _state_with_reasoning({"intent": "unclear"})
    orchestrator = RuntimeOrchestrator()

    def _keep_invalid(inner_state: RuntimeState) -> None:
        inner_state.reasoning_result = {"intent": "unclear"}

    orchestrator._full_reasoning = _keep_invalid  # type: ignore[assignment]

    orchestrator._validate_and_select_response_method(state)

    assert state.reasoning_corrective_retry_count == 2
    assert state.response_method == ResponseMethod.ASK
    assert state.retrieval_required is False


def test_step8_corrective_retry_budget_independent_from_gateway_retry_budget() -> None:
    # Trigger: missing required fields; fake sets gateway retry count to verify independence.
    state = _state_with_reasoning({"intent": "unclear"})
    orchestrator = RuntimeOrchestrator()

    def _fake_full_reasoning(inner_state: RuntimeState) -> None:
        inner_state.reasoning_gateway_retry_count = 2
        inner_state.reasoning_result = _base_reasoning(
            action_recommended="ASK",
            required_next_slots=["core_problem"],
        )

    orchestrator._full_reasoning = _fake_full_reasoning  # type: ignore[assignment]

    orchestrator._validate_and_select_response_method(state)

    assert state.reasoning_gateway_retry_count == 2
    assert state.reasoning_corrective_retry_count == 1
    assert state.response_method == ResponseMethod.ASK


def test_step8_schema_heavy_missing_core_fields_triggers_corrective_retry() -> None:
    state = _state_with_reasoning({"intent": "unclear"})
    orchestrator = RuntimeOrchestrator()

    def _fake_full_reasoning(inner_state: RuntimeState) -> None:
        inner_state.reasoning_result = _base_reasoning(
            action_recommended="ASK",
            intent="unclear",
            required_next_slots=["core_problem"],
        )

    orchestrator._full_reasoning = _fake_full_reasoning  # type: ignore[assignment]

    orchestrator._validate_and_select_response_method(state)

    assert state.reasoning_corrective_retry_count == 1
    assert state.reasoning_control is None
    assert state.response_method == ResponseMethod.ASK


def test_step8_schema_heavy_shape_errors_use_schema_feedback() -> None:
    state = _state_with_reasoning(
        _base_reasoning(
            case_slots="bad-shape",
            turn_strategy="bad-shape",
        )
    )
    orchestrator = RuntimeOrchestrator()
    captured_feedback: dict[str, object] = {}

    def _capture_full_reasoning(inner_state: RuntimeState) -> None:
        captured_feedback.update(inner_state.reasoning_control["validation_error_feedback"])
        inner_state.reasoning_result = _base_reasoning(
            action_recommended="ASK",
            intent="unclear",
            required_next_slots=["core_problem"],
        )

    orchestrator._full_reasoning = _capture_full_reasoning  # type: ignore[assignment]

    orchestrator._validate_and_select_response_method(state)

    assert captured_feedback["error_type"] == "schema_fail_heavy"
    assert "case_slots_not_object" in captured_feedback["error_codes"]
    assert "turn_strategy_not_object" not in captured_feedback["error_codes"]


def test_step8_turn_strategy_bad_shape_is_normalized_without_corrective_retry() -> None:
    state = _state_with_reasoning(
        _base_reasoning(
            turn_strategy="bad-shape",
            action_recommended="ASK",
            intent="unclear",
            required_next_slots=["core_problem"],
        )
    )

    RuntimeOrchestrator()._validate_and_select_response_method(state)

    assert state.reasoning_corrective_retry_count == 0
    assert state.response_method == ResponseMethod.ASK
    assert state.normalized_reasoning_result["turn_strategy"] == {"focus": "", "angle": "", "avoid": []}


def test_step8_no_schema_retry_when_reasoning_payload_is_complete() -> None:
    state = _state_with_reasoning(_base_reasoning(action_recommended="LISTEN", required_next_slots=[]))
    orchestrator = RuntimeOrchestrator()

    orchestrator._validate_and_select_response_method(state)

    assert state.response_method == ResponseMethod.LISTEN
    assert state.reasoning_corrective_retry_count == 0


def test_step8_persists_next_identity_signals_after_validation() -> None:
    state = _state_with_reasoning(
        _base_reasoning(
            action_recommended="LISTEN",
            required_next_slots=[],
            explicit_profile_facts_next=["works remotely"],
            style_signals_next=["prefers_brief_response"],
            user_state_signals_next=["overwhelmed"],
        )
    )

    RuntimeOrchestrator()._validate_and_select_response_method(state)

    profile, preference, user_state = IdentityStateStoreService().read_bundle_fields(identity=state.identity)
    assert state.runtime_bundle["identity_state_persisted_in_step8"] is True
    assert profile.get("facts") == ["works remotely"]
    assert preference.get("prefers_brief_response") in {True, None}
    assert user_state.get("primary_state") == "overwhelmed"
