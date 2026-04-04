"""RuleDecision contract — output from the RuleEngine."""

from typing import Any

from pydantic import BaseModel

from wismo.contracts.enums import CounselingMethod, CounselingSubmode


class RuleDecision(BaseModel):
    """Canonical output contract for the RuleEngine decision."""

    schema_version: str = "rule.v1"
    mode: CounselingMethod
    submode: CounselingSubmode = CounselingSubmode.NONE
    # safety_state kept as str until runtime vocabulary stabilises
    safety_state: str | None = None
    ui_hints: dict[str, Any] = {}
    override_reason: str | None = None
