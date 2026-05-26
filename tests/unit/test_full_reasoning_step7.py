"""Unit tests for Main Flow Step 7 full reasoning."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from accounts.models import GuestIdentity
from chat.models import Chat, ChatTurn
from chat.services import IdentityContext
from llm_ops.errors import LLMGatewayProviderError
from runtime.orchestrator import RuntimeOrchestrator, RuntimeState

pytestmark = pytest.mark.django_db


class StubGateway:
    """Gateway stub returning scripted responses or raising scripted errors."""

    def __init__(self, scripted_results: list[object]) -> None:
        self.scripted_results = scripted_results
        self.calls: list[dict] = []

    def complete(self, *, operation_key, turn, prompt_messages):  # noqa: D401
        """Capture call then return next scripted result."""

        self.calls.append(
            {
                "operation_key": operation_key,
                "turn": turn,
                "prompt_messages": prompt_messages,
            }
        )
        result = self.scripted_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(text=result)


def _build_state() -> RuntimeState:
    guest = GuestIdentity.objects.create()
    identity = IdentityContext(guest_identity=guest)
    chat = Chat.objects.create(guest_identity=guest, opening_input_text="open")
    turn = ChatTurn.objects.create(guest_identity=guest, chat=chat, user_message_text="current")

    return RuntimeState(
        request_payload=SimpleNamespace(message="hello"),
        identity=identity,
        quota_window=SimpleNamespace(),
        chat=chat,
        case=None,
        turn=turn,
        runtime_bundle={
            "current_message": "hello",
            "recent_turns": [{"user_message_text": "u1", "assistant_response_text": "a1"}],
            "context_summary": "summary",
            "user_profile": {},
            "user_preference": {},
            "user_state": {},
            "long_term_memory": [],
        },
        reasoning_result={},
    )


def test_step7_calls_full_reasoning_with_runtime_bundle_payload() -> None:
    gateway = StubGateway(
        [
            json.dumps(
                {
                    "intent": "unclear",
                    "action_recommended": "ASK",
                    "response_language": "en",
                    "required_next_slots": ["core_problem"],
                    "case_slots": {"core_problem": "x"},
                    "turn_strategy": {"focus": "f", "angle": "a", "avoid": []},
                    "explicit_profile_facts_next": [],
                    "style_signals_next": ["none"],
                    "user_state_signals_next": ["none"],
                    "suggested_chat_display_name": None,
                }
            )
        ]
    )
    orchestrator = RuntimeOrchestrator(llm_gateway=gateway)
    state = _build_state()

    orchestrator._full_reasoning(state)

    assert len(gateway.calls) == 1
    assert gateway.calls[0]["operation_key"].value == "full_reasoning"
    payload = json.loads(gateway.calls[0]["prompt_messages"][1]["content"])
    assert payload["runtime_bundle"]["current_message"] == "hello"
    assert payload["runtime_bundle"]["recent_turns"][0]["user_message_text"] == "u1"
    system_prompt = gateway.calls[0]["prompt_messages"][0]["content"]
    assert "action_recommended must be exactly one of: LISTEN, ASK, REFLECT, FOLLOWUP, TEACH." in system_prompt
    assert "turn_strategy definition" in system_prompt
    assert "style_signals_next are updated response-style preferences" in system_prompt
    assert "user_state_signals_next are updated emotional/mental-state signals" in system_prompt
    assert "explicit_profile_facts_next are cumulative factual profile facts" in system_prompt
    assert "suggested_chat_display_name" not in system_prompt


def test_step7_includes_reasoning_control_on_corrective_retry() -> None:
    gateway = StubGateway(["{}"])
    orchestrator = RuntimeOrchestrator(llm_gateway=gateway)
    state = _build_state()
    state.reasoning_control = {
        "is_corrective_retry": True,
        "retry_count": 1,
        "validation_error_feedback": {
            "error_type": "schema_fail_heavy",
            "error_codes": ["missing_required_field"],
            "must_fix_fields": ["intent"],
            "must_preserve": ["action_recommended"],
        },
    }

    orchestrator._full_reasoning(state)

    payload = json.loads(gateway.calls[0]["prompt_messages"][1]["content"])
    assert payload["reasoning_control"]["is_corrective_retry"] is True
    assert payload["reasoning_control"]["retry_count"] == 1


def test_step7_turn2_payload_includes_current_chat_display_name_for_renaming_decision() -> None:
    orchestrator = RuntimeOrchestrator(llm_gateway=StubGateway(["{}"]))
    state = _build_state()
    state.chat.chat_display_name = "Tên hiện tại"
    state.chat.save(update_fields=["chat_display_name"])
    state.needs_chat_display_name_suggestion = True
    state.chat_turn_number = 2

    prompt_messages = orchestrator._build_reasoning_prompt(state)
    payload = json.loads(prompt_messages[1]["content"])

    assert payload["chat_display_name_suggestion_context"]["chat_turn_number"] == 2
    assert payload["chat_display_name_suggestion_context"]["current_chat_display_name"] == "Tên hiện tại"


def test_step7_turn1_payload_includes_empty_current_chat_display_name() -> None:
    orchestrator = RuntimeOrchestrator(llm_gateway=StubGateway(["{}"]))
    state = _build_state()
    state.needs_chat_display_name_suggestion = True
    state.chat_turn_number = 1

    prompt_messages = orchestrator._build_reasoning_prompt(state)
    payload = json.loads(prompt_messages[1]["content"])

    assert payload["chat_display_name_suggestion_context"]["chat_turn_number"] == 1
    assert payload["chat_display_name_suggestion_context"]["current_chat_display_name"] == ""
    assert "suggested_chat_display_name" in prompt_messages[0]["content"]


def test_step7_retries_gateway_provider_errors_up_to_two_times() -> None:
    gateway = StubGateway(
        [
            LLMGatewayProviderError(),
            LLMGatewayProviderError(),
            "{}",
        ]
    )
    orchestrator = RuntimeOrchestrator(llm_gateway=gateway)
    state = _build_state()

    orchestrator._full_reasoning(state)

    assert len(gateway.calls) == 3
    assert state.reasoning_gateway_retry_count == 2


def test_step7_invalid_schema_falls_back_to_canonical_reasoning_result() -> None:
    gateway = StubGateway(["not-json"])
    orchestrator = RuntimeOrchestrator(llm_gateway=gateway)
    state = _build_state()

    orchestrator._full_reasoning(state)

    result = state.reasoning_result
    assert result["intent"] == "unclear"
    assert result["action_recommended"] == "ASK"
    assert result["style_signals_next"] == ["none"]
    assert set(result["case_slots"].keys()) == {
        "core_problem",
        "who_involved",
        "trigger",
        "timeframe",
        "prior_attempt",
        "goal",
        "desired_outcome",
    }


def test_step7_control_action_from_llm_is_normalized_to_ask() -> None:
    gateway = StubGateway(
        [
            json.dumps(
                {
                    "intent": "continue_previous_topic",
                    "action_recommended": "REDIRECT",
                    "response_language": "en",
                    "required_next_slots": [],
                    "case_slots": {"core_problem": "too much work", "goal": "finish thesis"},
                    "turn_strategy": {"focus": "f", "angle": "a", "avoid": []},
                    "explicit_profile_facts_next": [],
                    "style_signals_next": ["none"],
                    "user_state_signals_next": ["none"],
                    "suggested_chat_display_name": None,
                }
            )
        ]
    )
    orchestrator = RuntimeOrchestrator(llm_gateway=gateway)
    state = _build_state()

    orchestrator._full_reasoning(state)

    assert state.reasoning_result["action_recommended"] == "ASK"


def test_step7_response_language_is_normalized_from_llm_output() -> None:
    gateway = StubGateway(
        [
            json.dumps(
                {
                    "intent": "emotional_support",
                    "action_recommended": "LISTEN",
                    "response_language": "vi",
                    "required_next_slots": [],
                    "case_slots": {"core_problem": "x"},
                    "turn_strategy": {"focus": "f", "angle": "a", "avoid": []},
                    "explicit_profile_facts_next": [],
                    "style_signals_next": ["none"],
                    "user_state_signals_next": ["none"],
                    "suggested_chat_display_name": None,
                }
            )
        ]
    )
    orchestrator = RuntimeOrchestrator(llm_gateway=gateway)
    state = _build_state()

    orchestrator._full_reasoning(state)
    orchestrator._validate_and_select_response_method(state)

    assert state.reasoning_result["response_language"] == "vi"
    assert state.runtime_bundle["response_language"] == "vi"


def test_step7_response_language_rejects_generic_label_other() -> None:
    gateway = StubGateway(
        [
            json.dumps(
                {
                    "intent": "emotional_support",
                    "action_recommended": "LISTEN",
                    "response_language": "other",
                    "required_next_slots": [],
                    "case_slots": {"core_problem": "x"},
                    "turn_strategy": {"focus": "f", "angle": "a", "avoid": []},
                    "explicit_profile_facts_next": [],
                    "style_signals_next": ["none"],
                    "user_state_signals_next": ["none"],
                    "suggested_chat_display_name": None,
                }
            )
        ]
    )
    orchestrator = RuntimeOrchestrator(llm_gateway=gateway)
    state = _build_state()

    orchestrator._full_reasoning(state)
    feedback = orchestrator._schema_heavy_issue(state.reasoning_result)

    assert state.reasoning_result["response_language"] == "und"
    assert feedback is not None
    assert "response_language_invalid" in feedback["error_codes"]
