"""P2Output contract — phase evaluation result from the P2 analyzer."""

from pydantic import BaseModel, Field

from wismo.contracts.enums import CasePhase, CaseStatus, CounselingMethod, ReadinessLevel


class ContextAssessment(BaseModel):
    """Assessment of the current counseling context."""

    phase: CasePhase
    status: CaseStatus
    readiness: ReadinessLevel
    summary: str | None = None


class RecommendedAction(BaseModel):
    """Recommended counseling action for this turn."""

    method: CounselingMethod
    rationale: str | None = None


class P2Output(BaseModel):
    """Canonical output contract for the P2 phase evaluator."""

    schema_version: str = "p2.v1"
    context: ContextAssessment
    recommended_action: RecommendedAction
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    raw_response: str | None = None
