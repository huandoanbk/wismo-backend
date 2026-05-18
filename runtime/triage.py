"""Fast triage decision helpers for Main Flow Step 4."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from chat.models import Chat, ChatTurn
from llm_ops.errors import LLMGatewayError
from llm_ops.gateway import LLMGateway
from runtime.prompts import TRIAGE_CLASSIFIER_SYSTEM
from wismo.contracts.enums import OperationKey, ResponseMethod, TriageDecision

CANONICAL_TRIAGE_DECISIONS = {
    TriageDecision.CRISIS_HOTLINE_IMMEDIATE.value,
    TriageDecision.BLOCKED_MINOR.value,
    TriageDecision.HARD_REDIRECT.value,
    TriageDecision.POLICY_BYPASS_REFUSAL.value,
    TriageDecision.SPAM_OR_NON_CONVERSATIONAL.value,
    TriageDecision.CONTINUE_TO_FULL_REASONING.value,
}

OUT_OF_SCOPE_REQUEST_HINTS = [
    "tìm cho tôi",
    "tìm giúp",
    "gợi ý",
    "đề xuất",
    "recommend",
    "suggest",
    "where can i",
    "near me",
    "book",
    "đặt",
]

OUT_OF_SCOPE_DOMAIN_HINTS = [
    "quán ăn",
    "nhà hàng",
    "restaurant",
    "cafe",
    "quán cà phê",
    "khách sạn",
    "hotel",
    "du lịch",
    "travel",
    "vé máy bay",
    "flight",
    "thời tiết",
    "weather",
    "mua",
    "shopping",
    "coin",
    "bitcoin",
    "chứng khoán",
    "stock",
]

@dataclass(frozen=True)
class TriageResult:
    """Resolved Step 4 triage decision and provenance."""

    decision: TriageDecision
    source: str
    short_reason: str = ""
    confidence: str = "high"


@dataclass(frozen=True)
class ControlResponse:
    """Control-path response details for SSE emission.

    response_text is intentionally absent — FE renders copy from response_key via i18n catalog.
    """

    response_method: ResponseMethod
    response_key: str
    persist_turn: bool


class FastTriageService:
    """Rule-first triage service with LLM fallback."""

    def __init__(self, llm_gateway: LLMGateway) -> None:
        """Create service with gateway used for fallback classification."""

        self.llm_gateway = llm_gateway

    def decide(self, *, chat: Chat, current_turn: ChatTurn) -> TriageResult:
        """Resolve one triage decision for the current turn."""

        recent_user_turns = list(
            chat.turns.exclude(id=current_turn.id)
            .order_by("-created_at")
            .values_list("user_message_text", flat=True)[:3]
        )
        recent_user_turns.reverse()
        message = current_turn.user_message_text

        rule_result = self._rule_based(message=message, recent_user_turns=recent_user_turns)
        if rule_result is not None:
            return rule_result

        return self._llm_fallback(
            message=message,
            recent_user_turns=recent_user_turns,
            turn=current_turn,
        )

    def control_response_for_decision(self, decision: TriageDecision) -> ControlResponse | None:
        """Map control triage decisions to response method and i18n key."""

        if decision == TriageDecision.CRISIS_HOTLINE_IMMEDIATE:
            return ControlResponse(ResponseMethod.CRISIS_SAFE_ONLY, "crisis_hotline_immediate", True)
        if decision == TriageDecision.BLOCKED_MINOR:
            return ControlResponse(ResponseMethod.BLOCKED_MINOR, "blocked_minor", False)
        if decision == TriageDecision.HARD_REDIRECT:
            return ControlResponse(ResponseMethod.REDIRECT, "hard_redirect", False)
        if decision == TriageDecision.POLICY_BYPASS_REFUSAL:
            return ControlResponse(ResponseMethod.REFUSAL, "policy_bypass_refusal", False)
        if decision == TriageDecision.SPAM_OR_NON_CONVERSATIONAL:
            return ControlResponse(ResponseMethod.SPAM_REPLY, "spam_or_non_conversational", False)
        return None

    def _rule_based(self, *, message: str, recent_user_turns: list[str]) -> TriageResult | None:
        """Apply conservative deterministic rules before calling LLM."""

        text = " ".join([message, *recent_user_turns]).lower()

        if self._contains_any(
            text,
            [
                "tự tử",
                "muốn chết",
                "kill myself",
                "suicide",
                "hurt myself",
                "kill my self",
                "kill him",
                "kill her",
            ],
        ):
            return TriageResult(TriageDecision.CRISIS_HOTLINE_IMMEDIATE, "rule", "crisis_keywords")

        if self._contains_minor_age_signal(text):
            return TriageResult(TriageDecision.BLOCKED_MINOR, "rule", "minor_age_signal")

        if self._contains_any(
            text,
            ["chẩn đoán", "diagnose", "kê đơn", "prescribe", "medication", "trauma treatment"],
        ):
            return TriageResult(TriageDecision.HARD_REDIRECT, "rule", "out_of_scope_keywords")

        if self._contains_general_out_of_scope_request(message):
            return TriageResult(TriageDecision.HARD_REDIRECT, "rule", "out_of_scope_general_request")

        if self._contains_any(
            text,
            [
                "jailbreak",
                "ignore previous instructions",
                "ignore your instructions",
                "reveal system prompt",
                "show system prompt",
                "print system prompt",
                "bypass policy",
                "what are your instructions",
                "your hidden instructions",
                "internal instructions",
                "developer instructions",
                "prompt injection",
                "what model are you",
                "which model are you",
                "what ai are you",
                "which ai are you",
                "what version are you",
                "are you gpt",
                "are you claude",
                "are you gemini",
                "are you chatgpt",
                "bạn là mô hình",
                "bạn dùng model",
                "model của bạn",
                "system prompt của bạn",
                "prompt hệ thống",
            ],
        ):
            return TriageResult(TriageDecision.POLICY_BYPASS_REFUSAL, "rule", "policy_bypass_signal")

        stripped = message.strip().lower()
        if len(stripped) <= 2 or re.fullmatch(r"(.)\1{7,}", stripped):
            return TriageResult(TriageDecision.SPAM_OR_NON_CONVERSATIONAL, "rule", "spam_signal")

        return None

    def _llm_fallback(
        self,
        *,
        message: str,
        recent_user_turns: list[str] | None = None,
        turn: ChatTurn,
    ) -> TriageResult:
        """Call triage classifier operation and normalize its result."""

        normalized_recent_turns = [
            item.strip()
            for item in (recent_user_turns or [])
            if isinstance(item, str) and item.strip()
        ][:3]

        prompt_messages = [
            {
                "role": "system",
                "content": TRIAGE_CLASSIFIER_SYSTEM,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "current_message": message,
                        "recent_user_turns": normalized_recent_turns,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            completion = self.llm_gateway.complete(
                operation_key=OperationKey.TRIAGE_CLASSIFIER,
                turn=turn,
                prompt_messages=prompt_messages,
            )
        except LLMGatewayError:
            return TriageResult(TriageDecision.CONTINUE_TO_FULL_REASONING, "fallback")

        parsed = self._parse_triage_output(completion.text)
        if parsed is None:
            return TriageResult(TriageDecision.CONTINUE_TO_FULL_REASONING, "fallback")
        if (
            parsed["decision"] in {
                TriageDecision.BLOCKED_MINOR.value,
                TriageDecision.HARD_REDIRECT.value,
            }
            and parsed["confidence"] == "low"
        ):
            return TriageResult(
                decision=TriageDecision.CONTINUE_TO_FULL_REASONING,
                source="fallback",
                short_reason="llm_low_confidence_control_override",
                confidence=parsed["confidence"],
            )
        return TriageResult(
            decision=TriageDecision(parsed["decision"]),
            source="llm",
            short_reason=parsed["short_reason"],
            confidence=parsed["confidence"],
        )

    @staticmethod
    def _contains_any(text: str, phrases: list[str]) -> bool:
        """Return whether any phrase is present in normalized text."""

        return any(phrase in text for phrase in phrases)

    @staticmethod
    def _contains_minor_age_signal(text: str) -> bool:
        """Detect high-confidence under-18 self-age statements."""

        patterns = [
            r"\bi am (1[0-7]|[0-9])\b",
            r"\bi'?m (1[0-7]|[0-9])\b",
            r"\bunder 18\b",
            r"\b(1[0-7]) tuổi\b",
        ]
        return any(re.search(pattern, text) for pattern in patterns)

    def _contains_general_out_of_scope_request(self, message: str) -> bool:
        """Detect generic non-companion requests like local search, travel, or shopping."""

        text = re.sub(r"\s+", " ", message.strip().lower())
        if not text:
            return False

        has_request_hint = self._contains_any(text, OUT_OF_SCOPE_REQUEST_HINTS)
        has_domain_hint = self._contains_any(text, OUT_OF_SCOPE_DOMAIN_HINTS)
        if has_request_hint and has_domain_hint:
            return True

        return bool(
            re.search(
                r"\b(quán ăn|nhà hàng|restaurant|khách sạn|hotel)\b.*\b(ở|tại|in|near)\b",
                text,
            )
        )

    @staticmethod
    def _parse_triage_output(raw_text: str) -> dict[str, object] | None:
        """Normalize classifier output into canonical triage payload."""

        stripped = raw_text.strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                candidate = str(
                    parsed.get("triage_decision") or parsed.get("decision") or ""
                ).strip()
                if candidate in CANONICAL_TRIAGE_DECISIONS:
                    confidence = str(parsed.get("confidence") or "").strip().lower()
                    if confidence not in {"high", "medium", "low"}:
                        confidence = "low"
                    short_reason = str(parsed.get("short_reason") or "").strip()[:160]
                    if not short_reason:
                        # Backward-compat parse path for older model outputs.
                        raw_tags = parsed.get("reason_tags")
                        if isinstance(raw_tags, list):
                            for item in raw_tags:
                                if isinstance(item, str) and item.strip():
                                    short_reason = item.strip()[:160]
                                    break
                        if not short_reason:
                            short_reason = str(parsed.get("matched_span") or "").strip()[:160]
                    if candidate == TriageDecision.CONTINUE_TO_FULL_REASONING.value:
                        short_reason = ""
                    return {
                        "decision": candidate,
                        "confidence": confidence,
                        "short_reason": short_reason,
                    }
        except json.JSONDecodeError:
            pass

        if stripped in CANONICAL_TRIAGE_DECISIONS:
            return {
                "decision": stripped,
                "confidence": "low",
                "short_reason": "",
            }
        for candidate in CANONICAL_TRIAGE_DECISIONS:
            if candidate in stripped:
                return {
                    "decision": candidate,
                    "confidence": "low",
                    "short_reason": "" if candidate == TriageDecision.CONTINUE_TO_FULL_REASONING.value else "llm_text_contains_candidate",
                }
        return None
