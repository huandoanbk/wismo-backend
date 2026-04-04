"""Safety contracts — GuardResult, CrisisResult, SafetyDecision, SafetyConstraints."""

from pydantic import BaseModel

from wismo.contracts.enums import ConversationSafetyState, RiskLevel


class GuardResult(BaseModel):
    """Output of the InputGuard check."""

    schema_version: str = "guard.v1"
    passed: bool
    risk_level: RiskLevel = RiskLevel.NONE
    block_reason: str | None = None


class CrisisResult(BaseModel):
    """Output of crisis detection analysis."""

    crisis_detected: bool = False
    # tier kept as Optional[str] until tier vocabulary is stable
    tier: str | None = None
    keywords_matched: list[str] = []
    confidence: float = 0.0


class SafetyConstraints(BaseModel):
    """Runtime safety constraints applied to this turn."""

    response_mode_locked: bool = False
    allowed_methods: list[str] = []
    forbidden_topics: list[str] = []


class SafetyDecision(BaseModel):
    """Canonical safety decision for the current conversation turn."""

    schema_version: str = "safety.v1"
    state: ConversationSafetyState
    guard: GuardResult
    crisis: CrisisResult = CrisisResult()
    constraints: SafetyConstraints = SafetyConstraints()
    override_active: bool = False
