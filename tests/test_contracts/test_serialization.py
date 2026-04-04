"""Serialization round-trip and validation tests for canonical contract models."""

import pytest
from pydantic import ValidationError

from wismo.contracts import (
    CaseTransitionEvent,
    ChatDonePayload,
    ChatSendRequest,
    CrisisResult,
    GuardResult,
    OutboxEventEnvelope,
    P1Output,
    P2Output,
    PersonalizationConfig,
    RuleDecision,
    SafetyConstraints,
    SafetyDecision,
    SSEEvent,
    TracePayload,
    WismoError,
)
from wismo.contracts.enums import (
    CasePhase,
    CaseStatus,
    ConversationSafetyState,
    CounselingMethod,
    CounselingSubmode,
    EmotionShift,
    EmotionTag,
    Intent,
    OutboxDeliveryState,
    ReadinessLevel,
    RiskLevel,
)
from wismo.contracts.p1 import EmotionSignal
from wismo.contracts.p2 import ContextAssessment, RecommendedAction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _roundtrip(model_cls, instance):
    """Serialize and reconstruct a model; return the reconstructed instance."""
    data = instance.model_dump()
    return model_cls(**data)


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

def test_p1output_roundtrip() -> None:
    original = P1Output(
        intent=Intent.RELATED,
        emotion=EmotionSignal(primary=EmotionTag.ANXIOUS, shift=EmotionShift.ESCALATING, severity=5),
        confidence=0.9,
    )
    restored = _roundtrip(P1Output, original)
    assert restored == original


def test_p2output_roundtrip() -> None:
    original = P2Output(
        context=ContextAssessment(
            phase=CasePhase.UNDERSTAND,
            status=CaseStatus.ACTIVE,
            readiness=ReadinessLevel.EXPLORING,
        ),
        recommended_action=RecommendedAction(method=CounselingMethod.LISTEN),
    )
    restored = _roundtrip(P2Output, original)
    assert restored == original


def test_rule_decision_roundtrip() -> None:
    original = RuleDecision(
        mode=CounselingMethod.REFLECT,
        submode=CounselingSubmode.REFLECTION,
    )
    restored = _roundtrip(RuleDecision, original)
    assert restored == original


def test_safety_decision_roundtrip() -> None:
    original = SafetyDecision(
        state=ConversationSafetyState.NORMAL,
        guard=GuardResult(passed=True, risk_level=RiskLevel.NONE),
    )
    restored = _roundtrip(SafetyDecision, original)
    assert restored == original


def test_guard_result_roundtrip() -> None:
    original = GuardResult(passed=False, risk_level=RiskLevel.HIGH, block_reason="crisis")
    restored = _roundtrip(GuardResult, original)
    assert restored == original


def test_chat_done_payload_roundtrip() -> None:
    original = ChatDonePayload(
        request_id="req-1",
        session_id="sess-1",
        final_text="Xin chào",
    )
    restored = _roundtrip(ChatDonePayload, original)
    assert restored == original


def test_chat_send_request_roundtrip() -> None:
    original = ChatSendRequest(content="Tôi cần giúp đỡ")
    restored = _roundtrip(ChatSendRequest, original)
    assert restored == original


def test_outbox_envelope_has_idempotency_key() -> None:
    envelope = OutboxEventEnvelope(
        idempotency_key="key-abc",
        event_type="session.completed",
        created_at="2026-04-04T00:00:00Z",
    )
    assert envelope.idempotency_key == "key-abc"
    assert envelope.event_type == "session.completed"
    assert envelope.delivery_state == OutboxDeliveryState.PENDING


def test_wismo_error_roundtrip() -> None:
    original = WismoError(
        error_code="E001",
        error_category="system",
        http_status=500,
        user_message="Đã xảy ra lỗi.",
    )
    restored = _roundtrip(WismoError, original)
    assert restored == original


def test_trace_payload_roundtrip() -> None:
    original = TracePayload(
        request_id="req-1",
        turn_id="turn-1",
        session_id="sess-1",
        timestamps={"start": "2026-04-04T00:00:00Z"},
        latencies_ms={"p1": 120},
    )
    restored = _roundtrip(TracePayload, original)
    assert restored == original


def test_case_transition_event_roundtrip() -> None:
    original = CaseTransitionEvent(
        case_id="case-1",
        from_phase=CasePhase.UNDERSTAND,
        to_phase=CasePhase.ILLUMINATE,
        from_status=CaseStatus.ACTIVE,
        to_status=CaseStatus.PROGRESSING,
    )
    restored = _roundtrip(CaseTransitionEvent, original)
    assert restored == original


def test_personalization_config_roundtrip() -> None:
    original = PersonalizationConfig(tone="warm", depth="deep")
    restored = _roundtrip(PersonalizationConfig, original)
    assert restored == original


def test_contract_versions_13_entries() -> None:
    from wismo.contracts import CONTRACT_VERSIONS
    assert len(CONTRACT_VERSIONS) == 13


# ---------------------------------------------------------------------------
# schema_version defaults
# ---------------------------------------------------------------------------

def test_sse_event_schema_version() -> None:
    event = SSEEvent(type="thinking", request_id="req-1")
    assert event.schema_version == "sse.v1"


def test_chat_done_payload_schema_version() -> None:
    payload = ChatDonePayload(request_id="req-1", session_id="sess-1", final_text="x")
    assert payload.schema_version == "chat-done.v1"


def test_chat_send_request_schema_version() -> None:
    req = ChatSendRequest(content="hello")
    assert req.schema_version == "chat-send.v1"


def test_outbox_envelope_schema_version() -> None:
    envelope = OutboxEventEnvelope(
        idempotency_key="k",
        event_type="evt",
        created_at="2026-01-01T00:00:00Z",
    )
    assert envelope.schema_version == "outbox.v1"


def test_wismo_error_canonical_fields() -> None:
    err = WismoError(
        error_code="E002",
        error_category="auth",
        http_status=401,
        user_message="Không có quyền.",
    )
    assert err.error_code == "E002"
    assert err.error_category == "auth"
    assert err.http_status == 401
    assert err.frontend_state == "error"
    assert err.user_message == "Không có quyền."
    assert err.retryable is False
    assert err.request_id is None


def test_trace_payload_canonical_fields() -> None:
    trace = TracePayload(request_id="req-x", turn_id="t-1", session_id="s-1")
    assert trace.request_id == "req-x"
    assert trace.turn_id == "t-1"
    assert trace.session_id == "s-1"
    assert isinstance(trace.timestamps, dict)
    assert isinstance(trace.latencies_ms, dict)


# ---------------------------------------------------------------------------
# Validation constraint tests
# ---------------------------------------------------------------------------

def test_p1_severity_must_be_0_to_10() -> None:
    with pytest.raises(ValidationError):
        EmotionSignal(primary=EmotionTag.CALM, shift=EmotionShift.STABLE, severity=15)


def test_p1_confidence_must_be_0_to_1() -> None:
    with pytest.raises(ValidationError):
        P1Output(
            intent=Intent.RELATED,
            emotion=EmotionSignal(primary=EmotionTag.CALM, shift=EmotionShift.STABLE),
            confidence=1.5,
        )


def test_chat_send_content_not_empty() -> None:
    with pytest.raises(ValidationError):
        ChatSendRequest(content="")


def test_chat_send_content_max_2000() -> None:
    with pytest.raises(ValidationError):
        ChatSendRequest(content="x" * 2001)
