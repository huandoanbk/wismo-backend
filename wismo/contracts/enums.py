"""Canonical string-backed enums shared across WISMO contracts."""

from enum import StrEnum


class ConversationSafetyState(StrEnum):
    """Canonical safety states for conversation handling."""

    NORMAL = "NORMAL"
    GUARDED = "GUARDED"
    MODERATE_RISK_SAFE_ONLY = "MODERATE_RISK_SAFE_ONLY"
    HIGH_RISK_LISTEN_ONLY = "HIGH_RISK_LISTEN_ONLY"
    CRISIS_ONLY = "CRISIS_ONLY"
    BLOCKED_MINOR = "BLOCKED_MINOR"
    BLOCKED_OUT_OF_SCOPE = "BLOCKED_OUT_OF_SCOPE"


class CaseStatus(StrEnum):
    """Canonical lifecycle statuses for a case."""

    ACTIVE = "active"
    PROGRESSING = "progressing"
    PAUSED = "paused"
    STALLED = "stalled"
    RESOLVED = "resolved"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class CasePhase(StrEnum):
    """Canonical phases for case progression."""

    UNDERSTAND = "understand"
    ILLUMINATE = "illuminate"
    FOLLOWUP = "followup"


class CounselingMethod(StrEnum):
    """Canonical runtime counseling methods."""

    LISTEN = "LISTEN"
    ASK = "ASK"
    REFLECT = "REFLECT"
    TEACH = "TEACH"
    FOLLOWUP = "FOLLOWUP"
    REDIRECT = "REDIRECT"
    CRISIS_SAFE_ONLY = "CRISIS_SAFE_ONLY"


class CounselingSubmode(StrEnum):
    """Canonical counseling submodes."""

    REFLECTION = "reflection"
    CLARIFYING_QUESTION = "clarifying_question"
    BODY_AWARENESS = "body_awareness"
    STORY = "story"
    RESOURCE_REDIRECT = "resource_redirect"
    FOLLOWUP_CHECK = "followup_check"
    NONE = "none"


class EmotionTag(StrEnum):
    """Canonical emotional labels produced by analyzers."""

    CALM = "calm"
    ANXIOUS = "anxious"
    STRESSED = "stressed"
    SAD = "sad"
    ANGRY = "angry"
    CONFUSED = "confused"
    HOPEFUL = "hopeful"
    OVERWHELMED = "overwhelmed"
    GRATEFUL = "grateful"
    NEUTRAL_UNKNOWN = "neutral_unknown"


class EmotionShift(StrEnum):
    """Canonical change directions for emotional state."""

    STABLE = "stable"
    ESCALATING = "escalating"
    DE_ESCALATING = "de_escalating"
    NEW_TOPIC = "new_topic"
    UNKNOWN = "unknown"


class Sensitivity(StrEnum):
    """Canonical sensitivity tiers for content and data."""

    PUBLIC_SAFE = "public_safe"
    PRIVATE_SAFE = "private_safe"
    CLINICAL_SENSITIVE = "clinical_sensitive"


class ConsentState(StrEnum):
    """Canonical user consent states."""

    NO_CONSENT = "no_consent"
    CONSENTED_V1 = "consented_v1"
    RECONSENT_REQUIRED = "reconsent_required"
    WITHDRAWN_PENDING_DELETE = "withdrawn_pending_delete"
    DELETED = "deleted"


class SessionState(StrEnum):
    """Canonical chat session states."""

    OPENED = "opened"
    STREAMING = "streaming"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    TIMEOUT_CLOSED = "timeout_closed"
    VALIDATOR_REJECTED = "validator_rejected"


class OutboxDeliveryState(StrEnum):
    """Canonical outbox delivery lifecycle states."""

    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class ReadinessLevel(StrEnum):
    """Canonical readiness levels for change-oriented progress."""

    NOT_READY = "not_ready"
    EXPLORING = "exploring"
    INSIGHT = "insight"
    SELF_RESOLVING = "self_resolving"


class RiskLevel(StrEnum):
    """Canonical risk levels used across safety-related contracts."""

    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class OutOfScopeType(StrEnum):
    """Canonical reasons a request is out of scope."""

    NONE = "none"
    MEDICATION = "medication"
    DIAGNOSIS = "diagnosis"
    TRAUMA = "trauma"
    SUBSTANCE = "substance"
    OTHER = "other"


class Intent(StrEnum):
    """Canonical intent classes shared by analyzers and rules."""

    RELATED = "RELATED"
    UNRELATED = "UNRELATED"
    UNSAFE = "UNSAFE"
    META_ATTACK = "META_ATTACK"
