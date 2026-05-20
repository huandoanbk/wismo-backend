"""Unit tests for Main Flow Step 10 prompt assembly."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.orchestrator import RuntimeState
from runtime.prompt_assembly import PromptAssemblyService
from wismo.contracts.enums import ResponseMethod


def _memory_segment(*, user_concern: str, updated_at: str) -> dict[str, object]:
    return {
        "user_concern_summary": user_concern,
        "assistant_approach_summary": "reflect",
        "user_response_summary": "engaged",
        "state_shift": "clearer",
        "open_loops": ["next step"],
        "updated_at": updated_at,
    }


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
            "long_term_memory": [
                _memory_segment(user_concern="oldest", updated_at="2026-05-01T10:00:00+00:00"),
                _memory_segment(user_concern="middle", updated_at="2026-05-03T10:00:00+00:00"),
                _memory_segment(user_concern="newer", updated_at="2026-05-05T10:00:00+00:00"),
                _memory_segment(user_concern="latest", updated_at="2026-05-07T10:00:00+00:00"),
            ],
        },
        normalized_reasoning_result={
            "intent": "ask_teaching_or_perspective",
            "case_slots": {"core_problem": "conflict with manager"},
            "required_next_slots": ["trigger", "goal"],
            "turn_strategy": {"focus": "continuity", "angle": "gentle", "avoid": ["sermon"]},
            "style_signals_next": ["prefers_brief_response"],
            "user_state_signals_next": ["overwhelmed"],
            "explicit_profile_facts_next": ["works under deadline pressure"],
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


@pytest.mark.parametrize(
    "method",
    [
        ResponseMethod.LISTEN,
        ResponseMethod.ASK,
        ResponseMethod.REFLECT,
        ResponseMethod.FOLLOWUP,
        ResponseMethod.TEACH,
    ],
)
def test_step10_all_modes_include_long_term_memory_block(method: ResponseMethod) -> None:
    retrieval_result = None
    if method == ResponseMethod.TEACH:
        retrieval_result = {
            "retrieval_unit_text": "grounded text",
            "retrieval_prompt_payload": {"source_title": "Source A", "content_text_for_prompt": "grounded text"},
        }
    state = _state(method=method, retrieval_result=retrieval_result)

    result = PromptAssemblyService().build(state=state)
    content = result.prompt_messages[1]["content"]

    assert "Long-term memory (latest 3 segments):" in content
    assert "User concern: latest" in content
    assert "User concern: newer" in content
    assert "User concern: middle" in content
    assert "User concern: oldest" not in content
    if method == ResponseMethod.TEACH:
        assert result.prompt_debug_meta["retrieval_included"] is True
        assert result.prompt_debug_meta["retrieval_unit_chars"] == len("grounded text")
        assert result.prompt_debug_meta["retrieval_unit_preview"] == "grounded text"
        assert result.prompt_debug_meta["retrieval_source_title"] == "Source A"


def test_step10_teach_fallback_to_listen_when_retrieval_missing() -> None:
    state = _state(method=ResponseMethod.TEACH, retrieval_result=None)

    result = PromptAssemblyService().build(state=state)

    assert result.prompt_debug_meta["builder_name"] == "build_listen_prompt"
    assert state.runtime_bundle["effective_response_method"] == "LISTEN"
    assert state.runtime_bundle["effective_response_method_reason"] == "teach_retrieval_unavailable"
    assert "Task: Write one final response text for user in LISTEN mode." in result.prompt_messages[0]["content"]
    assert "Current message:" in result.prompt_messages[1]["content"]
    assert result.prompt_debug_meta["retrieval_included"] is False
    assert result.prompt_debug_meta["retrieval_unit_chars"] == 0
    assert result.prompt_debug_meta["retrieval_unit_preview"] == ""


def test_step10_retrieval_preview_is_truncated_in_debug_meta() -> None:
    retrieval_text = "x" * 700
    state = _state(
        method=ResponseMethod.TEACH,
        retrieval_result={
            "retrieval_unit_text": retrieval_text,
            "retrieval_prompt_payload": {"source_title": "Source A", "content_text_for_prompt": retrieval_text},
        },
    )

    result = PromptAssemblyService().build(state=state)

    preview = result.prompt_debug_meta["retrieval_unit_preview"]
    assert isinstance(preview, str)
    assert preview.endswith("...[truncated]")
    assert len(preview) < len(retrieval_text)


@pytest.mark.parametrize("retrieval_result", [{}, {"retrieval_unit_text": ""}, {"retrieval_prompt_payload": {"content_text_for_prompt": ""}}])
def test_step10_teach_fallback_with_invalid_retrieval_payload(retrieval_result) -> None:
    state = _state(method=ResponseMethod.TEACH, retrieval_result=retrieval_result)

    result = PromptAssemblyService().build(state=state)

    assert result.prompt_debug_meta["builder_name"] == "build_listen_prompt"


def test_step10_compact_priority_and_keep_current_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.services import PromptAssemblyPolicy
    monkeypatch.setattr(
        "runtime.prompt_assembly.RuntimeConfigService.prompt_assembly_policy",
        lambda self: PromptAssemblyPolicy(max_estimated_tokens=200),
    )
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
    content = result.prompt_messages[1]["content"]
    assert "current-message-stable" in content
    assert retrieval_text in content
    summary_lines = [line for line in content.splitlines() if line.startswith("- Context summary:")]
    if summary_lines:
        assert len(summary_lines[0].removeprefix("- Context summary:").strip()) <= 500


def test_step10_compact_applied_false_when_threshold_not_exceeded() -> None:
    state = _state(method=ResponseMethod.ASK)
    state.runtime_bundle["current_message"] = "short msg"
    state.runtime_bundle["recent_turns"] = []
    state.runtime_bundle["context_summary"] = "short summary"

    result = PromptAssemblyService().build(state=state)

    assert result.prompt_debug_meta["compact_applied"] is False
