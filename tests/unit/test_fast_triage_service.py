"""Unit tests for fast triage service fallback behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from llm_ops.errors import LLM_GATEWAY_CONFIG_MISSING, LLMGatewayConfigurationError
from runtime.triage import FastTriageService
from wismo.contracts.enums import TriageDecision

pytestmark = pytest.mark.django_db


class _FailingGateway:
    """Gateway stub that always fails operation resolution."""

    def complete(self, **kwargs):  # noqa: ANN003
        raise LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_MISSING)


class _JsonGateway:
    """Gateway stub returning configured text response."""

    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, **kwargs):  # noqa: ANN003
        return SimpleNamespace(text=self.text)


class _CaptureGateway:
    """Gateway stub capturing the last complete() kwargs."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.last_kwargs: dict | None = None

    def complete(self, **kwargs):  # noqa: ANN003
        self.last_kwargs = kwargs
        return SimpleNamespace(text=self.text)


def test_triage_llm_error_falls_back_to_continue() -> None:
    service = FastTriageService(_FailingGateway())

    result = service._llm_fallback(  # noqa: SLF001 - explicit unit test of fallback branch
        message="normal undecidable message",
        turn=SimpleNamespace(),
    )

    assert result.decision == TriageDecision.CONTINUE_TO_FULL_REASONING
    assert result.source == "fallback"


def test_triage_llm_json_with_low_confidence_control_downgrades_to_continue() -> None:
    service = FastTriageService(
        _JsonGateway(
            text=(
                '{"triage_decision":"hard_redirect","confidence":"low",'
                '"short_reason":"uncertain_scope"}'
            )
        )
    )

    result = service._llm_fallback(  # noqa: SLF001
        message="normal undecidable message",
        turn=SimpleNamespace(),
    )

    assert result.decision == TriageDecision.CONTINUE_TO_FULL_REASONING
    assert result.source == "fallback"
    assert result.short_reason == "llm_low_confidence_control_override"


def test_triage_llm_json_high_confidence_control_kept() -> None:
    service = FastTriageService(
        _JsonGateway(
            text=(
                '{"triage_decision":"hard_redirect","confidence":"high",'
                '"short_reason":"medical_diagnosis_request"}'
            )
        )
    )

    result = service._llm_fallback(  # noqa: SLF001
        message="please diagnose me",
        turn=SimpleNamespace(),
    )

    assert result.decision == TriageDecision.HARD_REDIRECT
    assert result.source == "llm"
    assert result.confidence == "high"
    assert result.short_reason == "medical_diagnosis_request"


def test_triage_llm_malformed_json_falls_back_to_continue() -> None:
    service = FastTriageService(_JsonGateway(text="{not-json"))

    result = service._llm_fallback(  # noqa: SLF001
        message="normal undecidable message",
        turn=SimpleNamespace(),
    )

    assert result.decision == TriageDecision.CONTINUE_TO_FULL_REASONING
    assert result.source == "fallback"


def test_triage_llm_fallback_prompt_includes_recent_turns_for_disambiguation() -> None:
    gateway = _CaptureGateway(
        text='{"triage_decision":"continue_to_full_reasoning","confidence":"high","short_reason":""}'
    )
    service = FastTriageService(gateway)

    result = service._llm_fallback(  # noqa: SLF001
        message="tìm cho tôi quán ăn Việt ở Helsinki",
        recent_user_turns=["Tôi đang buồn quá", "luận văn tôi làm sợ không kịp"],
        turn=SimpleNamespace(),
    )

    assert result.decision == TriageDecision.CONTINUE_TO_FULL_REASONING
    assert gateway.last_kwargs is not None
    prompt_messages = gateway.last_kwargs["prompt_messages"]
    assert len(prompt_messages) == 2
    user_payload = prompt_messages[1]["content"]
    assert "current_message" in user_payload
    assert "recent_user_turns" in user_payload


def test_rule_based_general_out_of_scope_request_redirects() -> None:
    service = FastTriageService(_JsonGateway(text='{"triage_decision":"continue_to_full_reasoning"}'))

    result = service._rule_based(  # noqa: SLF001 - explicit unit test of deterministic rules
        message="tìm cho tôi quán ăn Việt ở Helsinki",
        recent_user_turns=[
            "Tôi đang buồn quá",
            "luận văn tôi làm sợ không kịp, tôi bị stress",
        ],
    )

    assert result is not None
    assert result.decision == TriageDecision.HARD_REDIRECT
    assert result.source == "rule"
    assert result.short_reason == "out_of_scope_general_request"


def test_rule_based_emotional_support_stays_non_redirect() -> None:
    service = FastTriageService(_JsonGateway(text='{"triage_decision":"continue_to_full_reasoning"}'))

    result = service._rule_based(  # noqa: SLF001
        message="Tôi đang stress vì luận văn không kịp deadline",
        recent_user_turns=[],
    )

    assert result is None
