"""CaseTransitionEvent contract — case lifecycle transition event."""

from pydantic import BaseModel

from wismo.contracts.enums import CasePhase, CaseStatus


class CaseTransitionEvent(BaseModel):
    """Canonical event emitted when a case transitions phase or status."""

    schema_version: str = "case-transition.v1"
    case_id: str
    from_phase: CasePhase | None = None
    to_phase: CasePhase | None = None
    from_status: CaseStatus | None = None
    to_status: CaseStatus | None = None
    triggered_at: str | None = None  # ISO-8601 string
    triggered_by: str | None = None
