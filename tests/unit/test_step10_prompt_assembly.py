"""Unit tests for Main Flow Step 10 prompt assembly."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.orchestrator import RuntimeState
from runtime.prompt_assembly import PromptAssemblyService
from wismo.contracts.enums import ResponseMethod


def _state(*, method: ResponseMethod = ResponseMethod.ASK, retrieval_result=None, long_message: bool = False) -> RuntimeState:
    current_message = "I need help understanding this conflict"
    if long_message:
        current_message = "current-message-stable " + ("x" * 1200)

    return RuntimeState(
        request_payload=SimpleNamespace(message=current_message),
        identity=SimpleNamespace(owner_kwargs=lambda: {}),
        quota_window=SimpleNamespace(),
        response_method=method,
        runtime_bundle={
            "current_message": current_message,
            "recent_turns": [
                {
                    "user_message_text": "u" * 1200,
                    "assistant_response_text": "a" * 1200,
                },
                {
                    "user_message_text": "u2" * 900,
                    "assistant_response_text": "a2" * 900,
                },
                {
                    "user_message_text": "u3" * 900,
                    "assistant_response_text": "a3" * 900,
                },
            ],
            "context_summary": "summary " + ("z" * 2000),
            "retrieval_result": retrieval_result,
        },
        normalized_reasoning_result={
            "intent": "ask_teaching_or_perspective",
            "case_slots": {"core_problem": "conflict with manager"},
            "required_next_slots": ["trigger", "goal"],
            "turn_strategy": {"focus": "continuity", "angle": "gentle", "avoid": ["sermon"]},
            "style_signals": ["prefers_brief_response"],
            "user_state_signals": ["overwhelmed"],
        },
    )


def test_step10_builder_selection_and_contract() -> None:
    state = _state(method=ResponseMethod.ASK)

    result = PromptAssemblyService().build(state=state)

    assert len(result.prompt_messages) == 2
    assert result.prompt_messages[0]["role"] == "system"
    assert result.prompt_messages[1]["role"] == "user"
    assert result.prompt_debug_meta["builder_name"] == "build_ask_prompt"
    assert {"builder_name", "used_fields", "compact_applied", "estimated_tokens"} <= set(
        result.prompt_debug_meta
    )
    assert "effective_builder_name" not in result.prompt_debug_meta


def test_step10_teach_fallback_to_listen_when_retrieval_missing() -> None:
    state = _state(method=ResponseMethod.TEACH, retrieval_result=None)

    result = PromptAssemblyService().build(state=state)

    assert result.prompt_debug_meta["builder_name"] == "build_listen_prompt"
    assert state.runtime_bundle["effective_response_method"] == "LISTEN"
    payload = json.loads(result.prompt_messages[1]["content"])
    assert payload["instruction"].startswith("Write one final response text for user in LISTEN mode")


@pytest.mark.parametrize("retrieval_result", [{}, {"retrieval_unit_text": ""}, {"retrieval_prompt_payload": {"content_text_for_prompt": ""}}])
def test_step10_teach_fallback_with_invalid_retrieval_payload(retrieval_result) -> None:
    state = _state(method=ResponseMethod.TEACH, retrieval_result=retrieval_result)

    result = PromptAssemblyService().build(state=state)

    assert result.prompt_debug_meta["builder_name"] == "build_listen_prompt"


def test_step10_compact_priority_and_keep_current_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("runtime.prompt_assembly.MAX_PROMPT_ESTIMATED_TOKENS", 200)
    retrieval_text = "retrieval " + ("r" * 1600)
    state = _state(
        method=ResponseMethod.TEACH,
        retrieval_result={
            "retrieval_unit_text": retrieval_text,
            "retrieval_prompt_payload": {"content_text_for_prompt": retrieval_text},
        },
        long_message=True,
    )

    result = PromptAssemblyService().build(state=state)

    assert result.prompt_debug_meta["compact_applied"] is True
    payload = json.loads(result.prompt_messages[1]["content"])
    assert payload["current_message"].startswith("current-message-stable")
    assert len(payload["context_summary"]) <= 500
    assert payload["retrieval_unit_text"] == retrieval_text


def test_step10_injects_generation_validation_feedback() -> None:
    state = _state(method=ResponseMethod.ASK)
    state.runtime_bundle["generation_validation_feedback"] = {
        "error_codes": ["ASK_TOO_BROAD"],
        "rewrite_instruction": "Narrow to one concrete missing slot.",
        "keep_constraints": ["response_method", "final_safety_state"],
    }

    result = PromptAssemblyService().build(state=state)
    payload = json.loads(result.prompt_messages[1]["content"])

    assert payload["generation_validation_feedback"]["error_codes"] == ["ASK_TOO_BROAD"]
    assert "rewrite_instruction" in payload["generation_validation_feedback"]


def test_step10_compact_applied_false_when_threshold_not_exceeded() -> None:
    state = _state(method=ResponseMethod.ASK)
    state.runtime_bundle["current_message"] = "short msg"
    state.runtime_bundle["recent_turns"] = []
    state.runtime_bundle["context_summary"] = "short summary"

    result = PromptAssemblyService().build(state=state)

    assert result.prompt_debug_meta["compact_applied"] is False
