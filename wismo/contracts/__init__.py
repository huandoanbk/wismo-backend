"""Public contract exports for shared enums, version helpers, and contract models."""

from wismo.contracts.case import CaseTransitionEvent
from wismo.contracts.enums import (
    CasePhase,
    CaseStatus,
    ConsentState,
    ConversationSafetyState,
    CounselingMethod,
    CounselingSubmode,
    EmotionShift,
    EmotionTag,
    Intent,
    OutboxDeliveryState,
    OutOfScopeType,
    ReadinessLevel,
    RiskLevel,
    Sensitivity,
    SessionState,
)
from wismo.contracts.error import WismoError
from wismo.contracts.outbox import OutboxEventEnvelope
from wismo.contracts.p1 import P1Output
from wismo.contracts.p2 import P2Output
from wismo.contracts.rule import RuleDecision
from wismo.contracts.safety import CrisisResult, GuardResult, SafetyConstraints, SafetyDecision
from wismo.contracts.sse import ChatDonePayload, ChatSendRequest, SSEEvent
from wismo.contracts.style import PersonalizationConfig
from wismo.contracts.trace import TracePayload
from wismo.contracts.version import CONTRACT_VERSIONS, get_contract_version

__all__ = [
    # Enums
    "CasePhase",
    "CaseStatus",
    "ConsentState",
    "ConversationSafetyState",
    "CounselingMethod",
    "CounselingSubmode",
    "EmotionShift",
    "EmotionTag",
    "Intent",
    "OutOfScopeType",
    "OutboxDeliveryState",
    "ReadinessLevel",
    "RiskLevel",
    "Sensitivity",
    "SessionState",
    # Version helpers
    "CONTRACT_VERSIONS",
    "get_contract_version",
    # Contract models
    "CaseTransitionEvent",
    "ChatDonePayload",
    "ChatSendRequest",
    "CrisisResult",
    "GuardResult",
    "OutboxEventEnvelope",
    "P1Output",
    "P2Output",
    "PersonalizationConfig",
    "RuleDecision",
    "SafetyConstraints",
    "SafetyDecision",
    "SSEEvent",
    "TracePayload",
    "WismoError",
]
