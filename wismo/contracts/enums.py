"""Canonical enums for the MVP backend foundation."""

from enum import StrEnum


class ResponseMethod(StrEnum):
    """Runtime response methods shared by conversational and control paths."""

    LISTEN = "LISTEN"
    ASK = "ASK"
    REFLECT = "REFLECT"
    TEACH = "TEACH"
    FOLLOWUP = "FOLLOWUP"
    REDIRECT = "REDIRECT"
    CRISIS_SAFE_ONLY = "CRISIS_SAFE_ONLY"
    BLOCKED_MINOR = "BLOCKED_MINOR"
    REFUSAL = "REFUSAL"
    SPAM_REPLY = "SPAM_REPLY"


class TriageDecision(StrEnum):
    """Fast triage decisions at runtime step 4."""

    CRISIS_HOTLINE_IMMEDIATE = "crisis_hotline_immediate"
    BLOCKED_MINOR = "blocked_minor"
    HARD_REDIRECT = "hard_redirect"
    POLICY_BYPASS_REFUSAL = "policy_bypass_refusal"
    SPAM_OR_NON_CONVERSATIONAL = "spam_or_non_conversational"
    CONTINUE_TO_FULL_REASONING = "continue_to_full_reasoning"


class CaseStatus(StrEnum):
    """Lifecycle status for backend continuity cases."""

    ACTIVE = "active"
    PROGRESSING = "progressing"
    PAUSED = "paused"
    RESOLVED = "resolved"
    INACTIVE = "inactive"
    STALLED = "stalled"


class CasePhase(StrEnum):
    """MVP case phase."""

    UNDERSTAND = "understand"
    ILLUMINATE = "illuminate"
    FOLLOWUP = "followup"


class TurnStatus(StrEnum):
    """Minimal runtime status for a chat turn."""

    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class UsageAccountingStatus(StrEnum):
    """Usage accounting finalization status for a turn."""

    PENDING = "pending"
    FINALIZED = "finalized"
    PARTIAL = "partial"
    FAILED = "failed"


class Step12FinalizationStatus(StrEnum):
    """Synchronous post-turn finalization status."""

    PENDING = "pending"
    PROCESSING = "processing"
    FINALIZED = "finalized"
    PARTIAL = "partial"
    FAILED = "failed"


class LLMUsageStatus(StrEnum):
    """Status for one LLM operation usage event."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class LLMGatewayIntegrationKind(StrEnum):
    """Canonical integration kinds supported by LLM gateways."""

    OPENAI_COMPATIBLE = "openai_compatible"
    OPENAI_EMBEDDINGS_V1 = "openai_embeddings_v1"
    ANTHROPIC_NATIVE = "anthropic_native"
    AZURE_OPENAI_V1 = "azure_openai_v1"
    OPENAI_NATIVE = "openai_native"


class LLMGatewayMode(StrEnum):
    """Canonical message shaping modes for LLM gateways."""

    SINGLE_MESSAGE = "single_message"
    CONVERSATION = "conversation"


class OperationKey(StrEnum):
    """LLM operation keys required by the MVP runtime."""

    TRIAGE_CLASSIFIER = "triage_classifier"
    CASE_CLASSIFIER = "case_classifier"
    FULL_REASONING = "full_reasoning"
    RESPONSE_GENERATION = "response_generation"
    RESPONSE_VALIDATION = "response_validation"
    RETRIEVAL_QUERY_BUILDER = "retrieval_query_builder"
    RETRIEVAL_QUERY_EMBEDDING = "retrieval_query_embedding"
    RETRIEVAL_STITCH_VALIDATOR = "retrieval_stitch_validator"
    CONTEXT_SUMMARY_UPDATER = "context_summary_updater"
    LONG_TERM_MEMORY_EXTRACTOR = "long_term_memory_extractor"


CONVERSATIONAL_RESPONSE_METHODS = {
    ResponseMethod.LISTEN,
    ResponseMethod.ASK,
    ResponseMethod.REFLECT,
    ResponseMethod.TEACH,
    ResponseMethod.FOLLOWUP,
}

CONTROL_RESPONSE_METHODS = {
    ResponseMethod.REDIRECT,
    ResponseMethod.CRISIS_SAFE_ONLY,
    ResponseMethod.BLOCKED_MINOR,
    ResponseMethod.REFUSAL,
    ResponseMethod.SPAM_REPLY,
}
