"""Regression coverage for canonical contract enums and version helpers."""

import pytest

from wismo.contracts import (
    CONTRACT_VERSIONS,
    CasePhase,
    CaseStatus,
    ConsentState,
    ConversationSafetyState,
    CounselingMethod,
    CounselingSubmode,
    EmotionShift,
    EmotionTag,
    Intent,
    OutOfScopeType,
    OutboxDeliveryState,
    ReadinessLevel,
    RiskLevel,
    Sensitivity,
    SessionState,
    get_contract_version,
)


def test_conversation_safety_state_values_exact() -> None:
    assert {item.value for item in ConversationSafetyState} == {
        "NORMAL",
        "GUARDED",
        "MODERATE_RISK_SAFE_ONLY",
        "HIGH_RISK_LISTEN_ONLY",
        "CRISIS_ONLY",
        "BLOCKED_MINOR",
        "BLOCKED_OUT_OF_SCOPE",
    }


def test_case_status_values_exact() -> None:
    assert {item.value for item in CaseStatus} == {
        "active",
        "progressing",
        "paused",
        "stalled",
        "resolved",
        "inactive",
        "archived",
    }


def test_case_phase_values_exact() -> None:
    assert {item.value for item in CasePhase} == {
        "understand",
        "illuminate",
        "followup",
    }


def test_counseling_method_values_exact() -> None:
    assert {item.value for item in CounselingMethod} == {
        "LISTEN",
        "ASK",
        "REFLECT",
        "TEACH",
        "FOLLOWUP",
        "REDIRECT",
        "CRISIS_SAFE_ONLY",
    }


def test_counseling_submode_values_exact() -> None:
    assert {item.value for item in CounselingSubmode} == {
        "reflection",
        "clarifying_question",
        "body_awareness",
        "story",
        "resource_redirect",
        "followup_check",
        "none",
    }


def test_emotion_tag_values_exact() -> None:
    assert {item.value for item in EmotionTag} == {
        "calm",
        "anxious",
        "stressed",
        "sad",
        "angry",
        "confused",
        "hopeful",
        "overwhelmed",
        "grateful",
        "neutral_unknown",
    }


def test_emotion_shift_values_exact() -> None:
    assert {item.value for item in EmotionShift} == {
        "stable",
        "escalating",
        "de_escalating",
        "new_topic",
        "unknown",
    }


def test_sensitivity_values_exact() -> None:
    assert {item.value for item in Sensitivity} == {
        "public_safe",
        "private_safe",
        "clinical_sensitive",
    }


def test_consent_state_values_exact() -> None:
    assert {item.value for item in ConsentState} == {
        "no_consent",
        "consented_v1",
        "reconsent_required",
        "withdrawn_pending_delete",
        "deleted",
    }


def test_session_state_values_exact() -> None:
    assert {item.value for item in SessionState} == {
        "opened",
        "streaming",
        "completed",
        "abandoned",
        "timeout_closed",
        "validator_rejected",
    }


def test_outbox_delivery_state_values_exact() -> None:
    assert {item.value for item in OutboxDeliveryState} == {
        "pending",
        "dispatched",
        "failed",
        "dead_letter",
    }


def test_readiness_level_values_exact() -> None:
    assert {item.value for item in ReadinessLevel} == {
        "not_ready",
        "exploring",
        "insight",
        "self_resolving",
    }


def test_risk_level_values_exact() -> None:
    assert {item.value for item in RiskLevel} == {
        "none",
        "low",
        "moderate",
        "high",
    }


def test_out_of_scope_type_values_exact() -> None:
    assert {item.value for item in OutOfScopeType} == {
        "none",
        "medication",
        "diagnosis",
        "trauma",
        "substance",
        "other",
    }


def test_intent_values_exact() -> None:
    assert {item.value for item in Intent} == {
        "RELATED",
        "UNRELATED",
        "UNSAFE",
        "META_ATTACK",
    }


def test_contract_versions_13_entries() -> None:
    assert set(CONTRACT_VERSIONS) == {
        "P1Output",
        "P2Output",
        "RuleDecision",
        "SafetyDecision",
        "GuardResult",
        "SSEEvent",
        "ChatDonePayload",
        "ChatSendRequest",
        "OutboxEventEnvelope",
        "WismoError",
        "TracePayload",
        "CaseTransitionEvent",
        "PersonalizationConfig",
    }


def test_get_contract_version_p1() -> None:
    assert get_contract_version("P1Output") == "p1.v1"


def test_get_contract_version_unknown_raises() -> None:
    with pytest.raises(KeyError, match="Unknown contract: UnknownContract"):
        get_contract_version("UnknownContract")
