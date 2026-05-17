"""Contract enum tests for the MVP foundation."""

from wismo.contracts.enums import (
    CasePhase,
    CaseStatus,
    OperationKey,
    ResponseMethod,
    Step12FinalizationStatus,
    TriageDecision,
    TurnStatus,
    UsageAccountingStatus,
)


def values(enum_cls) -> set[str]:
    """Return enum values for assertion readability."""

    return {member.value for member in enum_cls}


def test_response_methods_match_mvp_foundation() -> None:
    """ResponseMethod contains conversational and control methods from MVP spec."""

    assert values(ResponseMethod) == {
        "LISTEN",
        "ASK",
        "REFLECT",
        "TEACH",
        "FOLLOWUP",
        "REDIRECT",
        "CRISIS_SAFE_ONLY",
        "BLOCKED_MINOR",
        "REFUSAL",
        "SPAM_REPLY",
    }


def test_core_runtime_enums_match_mvp_foundation() -> None:
    """Core runtime enums stay aligned with the BE implementation plan."""

    assert values(TriageDecision) == {
        "crisis_hotline_immediate",
        "blocked_minor",
        "hard_redirect",
        "policy_bypass_refusal",
        "spam_or_non_conversational",
        "continue_to_full_reasoning",
    }
    assert values(CaseStatus) == {"active", "progressing", "paused", "resolved", "inactive", "stalled"}
    assert values(CasePhase) == {"understand", "illuminate", "followup"}
    assert values(TurnStatus) == {"received", "processing", "completed", "failed"}
    assert values(UsageAccountingStatus) == {"pending", "finalized", "partial", "failed"}
    assert values(Step12FinalizationStatus) == {
        "pending",
        "processing",
        "finalized",
        "partial",
        "failed",
    }


def test_operation_keys_include_mvp_llm_operations() -> None:
    """OperationKey covers all LLM operations named by the MVP spec."""

    assert values(OperationKey) == {
        "triage_classifier",
        "case_classifier",
        "full_reasoning",
        "response_generation",
        "response_validation",
        "retrieval_query_builder",
        "retrieval_query_embedding",
        "retrieval_stitch_validator",
        "context_summary_updater",
        "long_term_memory_extractor",
    }
