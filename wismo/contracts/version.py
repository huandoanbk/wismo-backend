"""Version helpers for immediate-need public contracts."""

CONTRACT_VERSIONS = {
    "P1Output": "p1.v1",
    "P2Output": "p2.v1",
    "RuleDecision": "rule.v1",
    "SafetyDecision": "safety.v1",
    "GuardResult": "guard.v1",
    "SSEEvent": "sse.v1",
    "ChatDonePayload": "chat-done.v1",
    "ChatSendRequest": "chat-send.v1",
    "OutboxEventEnvelope": "outbox.v1",
    "WismoError": "error.v1",
    "TracePayload": "trace.v1",
    "CaseTransitionEvent": "case-transition.v1",
    "PersonalizationConfig": "style.v1",
}


def get_contract_version(contract_name: str) -> str:
    """Return the canonical version string for a named contract."""

    if contract_name not in CONTRACT_VERSIONS:
        raise KeyError(f"Unknown contract: {contract_name}")
    return CONTRACT_VERSIONS[contract_name]
