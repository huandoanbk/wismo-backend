"""Branch tests for Step 6/7/8 — covering gaps not in existing unit tests.

Step 6: D.1 recent_turns capped at 5
Step 7: non-transient LLM error raises immediately
Step 8: safety overrides, cleanup (D/E/G), passthrough mapping (8.6)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from accounts.models import GuestIdentity
from chat.models import Case, Chat, ChatTurn
from chat.services import IdentityContext
from llm_ops.errors import (
    LLMGatewayError,
)
from runtime.orchestrator import RuntimeOrchestrator, RuntimeState
from runtime.services import RuntimeBundleService
from wismo.contracts.enums import ResponseMethod, TurnStatus

pytestmark = pytest.mark.django_db


# ── shared helpers ────────────────────────────────────────────────


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


def _base_reasoning(**overrides) -> dict:
    data = {
        "risk_flags": ["none"],
        "intent": "emotional_support",
        "action_recommended": "LISTEN",
        "is_context_sufficient": True,
        "required_next_slots": [],
        "case_slots": {
            "core_problem": "stress",
            "who_involved": "self",
            "trigger": "work",
            "timeframe": "recent",
            "prior_attempt": "none",
            "goal": "feel better",
            "desired_outcome": "calm",
        },
        "turn_strategy": {"focus": "empathy", "angle": "gentle", "avoid": "advice"},
        "explicit_profile_facts": [],
        "style_signals": ["none"],
        "user_state_signals": ["none"],
        "suggested_chat_display_name": None,
    }
    data.update(overrides)
    return data


# ══════════════════════════════════════════════════════════════════
#  STEP 6 — D.1: recent_turns capped at 5, ordered old → new
# ══════════════════════════════════════════════════════════════════

def test_step6_recent_turns_capped_at_5() -> None:
    """D.1: bundle loads max 5 completed turns even when chat has more."""
    guest = GuestIdentity.objects.create()
    identity = IdentityContext(guest_identity=guest)
    chat = Chat.objects.create(guest_identity=guest, opening_input_text="open")
    case = Case.objects.create(guest_identity=guest)
    chat.case = case
    chat.save(update_fields=["case"])

    # Create 8 completed turns
    for i in range(8):
        ChatTurn.objects.create(
            guest_identity=guest,
            chat=chat,
            user_message_text=f"msg {i}",
            status=TurnStatus.COMPLETED.value,
            assistant_response_text=f"resp {i}",
        )

    bundle = RuntimeBundleService().build_bundle(
        chat=chat,
        turn=ChatTurn.objects.filter(chat=chat).last(),
        case=case,
        identity=identity,
        current_message="new message",
    )

    assert len(bundle["recent_turns"]) == 5


def test_step6_recent_turns_ordered_old_to_new() -> None:
    """D.1: bundle orders turns from oldest to most recent."""
    guest = GuestIdentity.objects.create()
    identity = IdentityContext(guest_identity=guest)
    chat = Chat.objects.create(guest_identity=guest, opening_input_text="open")
    case = Case.objects.create(guest_identity=guest)
    chat.case = case
    chat.save(update_fields=["case"])

    for i in range(3):
        ChatTurn.objects.create(
            guest_identity=guest,
            chat=chat,
            user_message_text=f"msg {i}",
            status=TurnStatus.COMPLETED.value,
            assistant_response_text=f"resp {i}",
        )

    # Current turn is separate — excluded from recent_turns by the bundle loader
    current_turn = ChatTurn.objects.create(
        guest_identity=guest,
        chat=chat,
        user_message_text="current",
        status=TurnStatus.PROCESSING.value,
    )

    bundle = RuntimeBundleService().build_bundle(
        chat=chat,
        turn=current_turn,
        case=case,
        identity=identity,
        current_message="current",
    )

    texts = [t["user_message_text"] for t in bundle["recent_turns"]]
    assert texts == ["msg 0", "msg 1", "msg 2"]


# ══════════════════════════════════════════════════════════════════
#  STEP 7 — non-transient LLM error raises immediately
# ══════════════════════════════════════════════════════════════════

def test_step7_non_transient_error_raises_without_retry() -> None:
    """E.2: non-transient gateway error propagates immediately, no retry."""
    from llm_ops.errors import LLM_GATEWAY_CONFIG_MISSING

    state = _state_with_reasoning(_base_reasoning())
    state.runtime_bundle = {
        "current_message": "hello",
        "recent_turns": [],
        "context_summary": "",
        "user_profile": {},
        "user_preference": {},
        "user_state": {},
        "long_term_memory": [],
    }

    call_count = 0

    def _always_config_error(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise LLMGatewayError(LLM_GATEWAY_CONFIG_MISSING, 500)

    from llm_ops.gateway import LLMGateway
    with patch.object(LLMGateway, "complete", side_effect=_always_config_error):
        with pytest.raises(LLMGatewayError):
            RuntimeOrchestrator()._full_reasoning(state)

    assert call_count == 1


def test_step8_applies_suggested_chat_display_name_for_first_turn() -> None:
    """Step 8 applies suggested chat title only when first-turn suggestion is enabled."""

    state = _state_with_reasoning(_base_reasoning(
        action_recommended="LISTEN",
        is_context_sufficient=True,
        required_next_slots=[],
        suggested_chat_display_name="Áp lực luận văn",
    ))
    state.needs_chat_display_name_suggestion = True

    RuntimeOrchestrator()._validate_and_select_response_method(state)
    state.chat.refresh_from_db()

    assert state.chat.chat_display_name == "Áp lực luận văn"


# ══════════════════════════════════════════════════════════════════
#  STEP 8 — D: required_next_slots cleanup
# ══════════════════════════════════════════════════════════════════

def test_step8_non_ask_action_clears_required_next_slots() -> None:
    """D: action != ASK but required_next_slots non-empty → cleared."""
    state = _state_with_reasoning(_base_reasoning(
        intent="emotional_support",
        action_recommended="LISTEN",
        is_context_sufficient=True,
        required_next_slots=["core_problem", "goal"],
    ))
    RuntimeOrchestrator()._validate_and_select_response_method(state)
    assert state.response_method == ResponseMethod.LISTEN
    assert state.normalized_reasoning_result["required_next_slots"] == []


def test_step8_required_slots_outside_allowlist_filtered() -> None:
    """D: required_next_slots with out-of-allowlist values → filtered out."""
    state = _state_with_reasoning(_base_reasoning(
        intent="emotional_support",
        action_recommended="ASK",
        is_context_sufficient=False,
        required_next_slots=["core_problem", "invalid_slot_xyz"],
    ))
    RuntimeOrchestrator()._validate_and_select_response_method(state)
    slots = state.normalized_reasoning_result["required_next_slots"]
    assert "invalid_slot_xyz" not in slots
    assert "core_problem" in slots


# ══════════════════════════════════════════════════════════════════
#  STEP 8 — E: fulfilled required_next_slots removed
# ══════════════════════════════════════════════════════════════════

def test_step8_fulfilled_slots_removed_from_required() -> None:
    """E: slot already filled in case_slots removed from required_next_slots."""
    state = _state_with_reasoning(_base_reasoning(
        intent="emotional_support",
        action_recommended="ASK",
        is_context_sufficient=False,
        required_next_slots=["core_problem", "goal"],
        case_slots={
            "core_problem": "anxiety at work",  # already filled
            "who_involved": "",
            "trigger": "",
            "timeframe": "",
            "prior_attempt": "",
            "goal": "",
            "desired_outcome": "",
        },
    ))
    RuntimeOrchestrator()._validate_and_select_response_method(state)
    slots = state.normalized_reasoning_result["required_next_slots"]
    assert "core_problem" not in slots
    assert "goal" in slots


# ══════════════════════════════════════════════════════════════════
#  STEP 8 — G: style/user_state signals filtered
# ══════════════════════════════════════════════════════════════════

def test_step8_style_signals_outside_allowlist_filtered() -> None:
    """G: style_signals outside allowlist → dropped, default [none]."""
    state = _state_with_reasoning(_base_reasoning(
        style_signals=["prefers_gentle_tone", "unknown_style_signal"],
    ))
    RuntimeOrchestrator()._validate_and_select_response_method(state)
    signals = state.normalized_reasoning_result["style_signals"]
    assert "unknown_style_signal" not in signals
    assert "prefers_gentle_tone" in signals


def test_step8_user_state_signals_outside_allowlist_filtered() -> None:
    """G: user_state_signals outside allowlist → dropped."""
    state = _state_with_reasoning(_base_reasoning(
        user_state_signals=["stable_enough", "GARBAGE_VALUE"],
    ))
    RuntimeOrchestrator()._validate_and_select_response_method(state)
    signals = state.normalized_reasoning_result["user_state_signals"]
    assert "GARBAGE_VALUE" not in signals
    assert "stable_enough" in signals


# ══════════════════════════════════════════════════════════════════
#  STEP 8 — 8.2: dedup risk_flags
# ══════════════════════════════════════════════════════════════════

def test_step8_duplicate_risk_flags_deduped() -> None:
    """8.2: duplicate values in risk_flags are removed."""
    state = _state_with_reasoning(_base_reasoning(
        risk_flags=["none", "none", "none"],
    ))
    RuntimeOrchestrator()._validate_and_select_response_method(state)
    flags = state.normalized_reasoning_result["risk_flags"]
    assert flags.count("none") == 1


# ══════════════════════════════════════════════════════════════════
#  STEP 8 — 8.6 normal conversational mapping
# ══════════════════════════════════════════════════════════════════

def test_step8_listen_maps_to_listen() -> None:
    """8.6: LISTEN → LISTEN."""
    state = _state_with_reasoning(_base_reasoning(
        action_recommended="LISTEN",
        intent="emotional_support",
        is_context_sufficient=True,
    ))
    RuntimeOrchestrator()._validate_and_select_response_method(state)
    assert state.response_method == ResponseMethod.LISTEN


def test_step8_reflect_maps_to_reflect() -> None:
    """8.6: REFLECT + self_understanding intent → REFLECT."""
    state = _state_with_reasoning(_base_reasoning(
        action_recommended="REFLECT",
        intent="self_understanding",
        is_context_sufficient=True,
    ))
    RuntimeOrchestrator()._validate_and_select_response_method(state)
    assert state.response_method == ResponseMethod.REFLECT


def test_step8_followup_maps_to_followup() -> None:
    """8.6: FOLLOWUP + continue_previous_topic → FOLLOWUP."""
    state = _state_with_reasoning(_base_reasoning(
        action_recommended="FOLLOWUP",
        intent="continue_previous_topic",
        is_context_sufficient=True,
    ))
    RuntimeOrchestrator()._validate_and_select_response_method(state)
    assert state.response_method == ResponseMethod.FOLLOWUP


def test_step8_ask_maps_to_ask() -> None:
    """8.6: ASK → ASK."""
    state = _state_with_reasoning(_base_reasoning(
        action_recommended="ASK",
        intent="emotional_support",
        is_context_sufficient=False,
        required_next_slots=["core_problem"],
    ))
    RuntimeOrchestrator()._validate_and_select_response_method(state)
    assert state.response_method == ResponseMethod.ASK
