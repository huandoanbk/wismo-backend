"""Unit tests for Main Flow Step 11 response generation/validation/persist flow."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from llm_ops.errors import LLM_RESPONSE_GENERATION_FAILED, LLMGatewayError, LLMGatewayProviderError
from runtime.response_generation import ResponseGenerationService
from wismo.contracts.enums import OperationKey, ResponseMethod


class DummyGateway:
    """Gateway stub for Step 11 service tests."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def complete(self, *, operation_key, turn, prompt_messages):  # noqa: D401, ANN001
        self.calls.append(
            {
                "operation_key": operation_key,
                "turn": turn,
                "prompt_messages": prompt_messages,
            }
        )
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(text=value)


def _state(*, method: ResponseMethod = ResponseMethod.ASK, retrieval_result=None):
    return SimpleNamespace(
        response_method=method,
        final_safety_state="normal",
        turn=SimpleNamespace(id="turn-1"),
        runtime_bundle={
            "current_message": "hello",
            "prompt_messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "usr"},
            ],
            "retrieval_result": retrieval_result,
        },
        normalized_reasoning_result={
            "intent": "ask_how_to_respond",
            "case_slots": {"core_problem": "x"},
            "required_next_slots": ["goal"],
        },
    )


def test_step11_success_generation_and_validation_pass() -> None:
    gateway = DummyGateway([
        "candidate text",
        json.dumps(
            {
                "pass": True,
                "severity": "light",
                "error_codes": [],
                "rewrite_instruction": "",
                "fallback_recommended": None,
            }
        ),
    ])
    state = _state()

    result = ResponseGenerationService(gateway).run(state=state, rebuild_prompt=lambda s: None)

    assert result.response_text == "candidate text"
    assert result.metadata["fallback_used"] is False
    assert result.metadata["generation_retry_count"] == 0
    assert gateway.calls[0]["operation_key"] == OperationKey.RESPONSE_GENERATION
    assert gateway.calls[1]["operation_key"] == OperationKey.RESPONSE_VALIDATION


def test_step11_retry_loop_rebuilds_prompt_and_then_succeeds() -> None:
    gateway = DummyGateway([
        "first candidate",
        json.dumps({"pass": False, "severity": "hard", "error_codes": ["ASK_TOO_BROAD"], "rewrite_instruction": "Narrow", "fallback_recommended": "ASK"}),
        "second candidate",
        json.dumps({"pass": True, "severity": "light", "error_codes": [], "rewrite_instruction": "", "fallback_recommended": None}),
    ])
    state = _state()
    rebuild_calls: list[int] = []

    def _rebuild(inner_state):  # noqa: ANN001
        rebuild_calls.append(1)
        assert "generation_validation_feedback" in inner_state.runtime_bundle

    result = ResponseGenerationService(gateway).run(state=state, rebuild_prompt=_rebuild)

    assert result.response_text == "second candidate"
    assert result.metadata["generation_retry_count"] == 1
    assert len(rebuild_calls) == 1


def test_step11_exhausted_retry_raises_generation_failed() -> None:
    gateway = DummyGateway([
        "bad1",
        json.dumps({"pass": False, "severity": "hard", "error_codes": ["GENERAL_TONE_FAIL"], "rewrite_instruction": "Fix", "fallback_recommended": "ASK"}),
        "bad2",
        json.dumps({"pass": False, "severity": "hard", "error_codes": ["GENERAL_TONE_FAIL"], "rewrite_instruction": "Fix", "fallback_recommended": "ASK"}),
        "bad3",
        json.dumps({"pass": False, "severity": "hard", "error_codes": ["GENERAL_TONE_FAIL"], "rewrite_instruction": "Fix", "fallback_recommended": "ASK"}),
    ])
    state = _state(method=ResponseMethod.ASK)

    with pytest.raises(LLMGatewayError) as exc_info:
        ResponseGenerationService(gateway).run(state=state, rebuild_prompt=lambda s: None)

    assert exc_info.value.code == LLM_RESPONSE_GENERATION_FAILED
    assert exc_info.value.status_code == 500


def test_step11_validator_input_completeness_for_teach() -> None:
    gateway = DummyGateway([
        "teach candidate",
        json.dumps({"pass": True, "severity": "light", "error_codes": [], "rewrite_instruction": "", "fallback_recommended": None}),
    ])
    retrieval_result = {"retrieval_unit_text": "grounded text"}
    state = _state(method=ResponseMethod.TEACH, retrieval_result=retrieval_result)

    ResponseGenerationService(gateway).run(state=state, rebuild_prompt=lambda s: None)

    validator_payload = json.loads(gateway.calls[1]["prompt_messages"][1]["content"])
    assert validator_payload["candidate_response_text"] == "teach candidate"
    assert validator_payload["response_method"] == "TEACH"
    assert validator_payload["final_safety_state"] == "normal"
    assert validator_payload["current_message"] == "hello"
    assert "normalized_reasoning_result" in validator_payload
    assert validator_payload["retrieval_result"] == retrieval_result


def test_step11_validator_uses_effective_response_method_when_present() -> None:
    gateway = DummyGateway([
        "listen candidate",
        json.dumps({"pass": True, "severity": "light", "error_codes": [], "rewrite_instruction": "", "fallback_recommended": None}),
    ])
    state = _state(method=ResponseMethod.TEACH, retrieval_result=None)
    state.runtime_bundle["effective_response_method"] = "LISTEN"

    ResponseGenerationService(gateway).run(state=state, rebuild_prompt=lambda s: None)

    validator_payload = json.loads(gateway.calls[1]["prompt_messages"][1]["content"])
    assert validator_payload["response_method"] == "LISTEN"
    assert "retrieval_result" not in validator_payload


def test_step11_logic_validation_fail_skips_validator() -> None:
    gateway = DummyGateway(["   ", "   ", "   "])
    state = _state(method=ResponseMethod.ASK)

    with pytest.raises(LLMGatewayError) as exc_info:
        ResponseGenerationService(gateway).run(state=state, rebuild_prompt=lambda s: None)

    assert exc_info.value.code == LLM_RESPONSE_GENERATION_FAILED
    assert all(call["operation_key"] == OperationKey.RESPONSE_GENERATION for call in gateway.calls)


def test_step11_validation_result_keeps_raw_fallback_token() -> None:
    data = ResponseGenerationService._validation_result(
        passed=False,
        severity="hard",
        error_codes=["GENERAL_TONE_FAIL"],
        rewrite_instruction="Fix",
        fallback_recommended="unknown_token",
    )

    assert data["fallback_recommended"] is None
    assert data["raw_fallback_recommended"] == "UNKNOWN_TOKEN"


def test_step11_fail_closed_on_generation_gateway_error() -> None:
    gateway = DummyGateway([LLMGatewayProviderError()])
    state = _state(method=ResponseMethod.ASK)

    with pytest.raises(LLMGatewayProviderError):
        ResponseGenerationService(gateway).run(state=state, rebuild_prompt=lambda s: None)
