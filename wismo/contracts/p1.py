"""P1Output contract — situation analysis result from the P1 analyzer."""

from pydantic import BaseModel, Field

from wismo.contracts.enums import EmotionShift, EmotionTag, Intent, OutOfScopeType


class EmotionSignal(BaseModel):
    """Detected emotional state from user input."""

    primary: EmotionTag
    shift: EmotionShift
    severity: int = Field(default=0, ge=0, le=10)


class ContraindicationSignal(BaseModel):
    """Signals related to clinical contraindications."""

    detected: bool = False
    type: OutOfScopeType = OutOfScopeType.NONE
    detail: str | None = None


class ScopeSignal(BaseModel):
    """Signals related to topic scope."""

    in_scope: bool = True
    out_of_scope_type: OutOfScopeType = OutOfScopeType.NONE


class SafetySignal(BaseModel):
    """Safety-related signals from input analysis."""

    crisis_keywords_detected: bool = False
    self_harm_language: bool = False
    risk_escalation: bool = False


class ContentSignal(BaseModel):
    """General content classification signals."""

    topics: list[str] = Field(default_factory=list)
    language_code: str = "vi"


class SessionEndingSignal(BaseModel):
    """Signals indicating the user wants to end the session."""

    detected: bool = False
    explicit: bool = False


class P1Output(BaseModel):
    """Canonical output contract for the P1 situation analyzer."""

    schema_version: str = "p1.v1"
    intent: Intent
    emotion: EmotionSignal
    contraindication: ContraindicationSignal = Field(default_factory=ContraindicationSignal)
    scope: ScopeSignal = Field(default_factory=ScopeSignal)
    safety: SafetySignal = Field(default_factory=SafetySignal)
    content: ContentSignal = Field(default_factory=ContentSignal)
    session_ending: SessionEndingSignal = Field(default_factory=SessionEndingSignal)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    raw_response: str | None = None
