"""Step 11 response generation, validation, retry, and fallback service."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from llm_ops.errors import (
    LLM_GATEWAY_PROVIDER_ERROR,
    LLM_GATEWAY_PROVIDER_UNAVAILABLE,
    LLM_RESPONSE_GENERATION_FAILED,
    LLMGatewayError,
)
from llm_ops.gateway import LLMGateway
from runtime.prompts import RESPONSE_VALIDATION_SYSTEM
from wismo.contracts.enums import OperationKey, ResponseMethod

MAX_GENERATION_RETRIES = 3
RETRYABLE_PROVIDER_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_PROVIDER_ERROR_CODES = {LLM_GATEWAY_PROVIDER_ERROR, LLM_GATEWAY_PROVIDER_UNAVAILABLE}
MEDICAL_ADVICE_PATTERNS = (
    re.compile(
        r"(uống|dùng|tiêm|bôi|xịt|tăng|giảm|ngưng|ngừng|đổi)\W{0,20}(thuốc|liều|kháng sinh|paracetamol|ibuprofen|ssri|benzodiazepine)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(take|use|inject|apply|increase|decrease|stop|start)\W{0,20}(medication|medicine|drug|dose|antibiotic|ssri|benzodiazepine|painkiller)",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d+\s?(mg|ml)\b", re.IGNORECASE),
)
HARM_INSTRUCTION_PATTERNS = (
    re.compile(
        r"(hãy|cứ|nên|thử|you should|just)\W{0,20}(tự tử|tự làm hại|tự làm đau|cắt tay|cắt cổ tay|uống quá liều|nhảy lầu|treo cổ|kill yourself|self-harm|overdose)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(hãy|cứ|nên|you should|just)\W{0,20}(giết|đánh|đâm|đốt|kill|hurt|stab|burn)\W{0,20}(người|họ|ai đó|someone|them)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(go kill yourself)\b", re.IGNORECASE),
)
PROFANITY_PATTERNS = (
    re.compile(r"(đụ má|địt mẹ|đmm|dm mẹ|đéo|lồn|cặc|đĩ|vcl|vl|cc)\b", re.IGNORECASE),
    re.compile(r"\b(fuck|fucking|shit|bitch|asshole|motherfucker)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class Step11Result:
    """Canonical Step 11 outcome."""

    response_text: str
    metadata: dict[str, Any]


class ResponseGenerationService:
    """Execute Step 11 lifecycle using Main Flow/MVP contracts."""

    def __init__(self, llm_gateway: LLMGateway) -> None:
        self.llm_gateway = llm_gateway

    def run(self, *, state) -> Step11Result:
        """Generate, validate, and retry within Step 11 without rebuilding Step 10 prompt."""

        base_prompt_messages = state.runtime_bundle.get("prompt_messages", [])
        prompt_messages = base_prompt_messages
        retry_count = 0
        retry_reasons: list[str] = []
        last_validation = self._validation_result(
            passed=False,
            severity="hard",
            error_codes=["GENERAL_IRRELEVANT"],
            rewrite_instruction="",
            fallback_recommended=None,
        )

        while True:
            try:
                completion = self.llm_gateway.complete(
                    operation_key=OperationKey.RESPONSE_GENERATION,
                    turn=state.turn,
                    prompt_messages=prompt_messages,
                )
            except LLMGatewayError as exc:
                if self._is_retryable_generation_error(exc) and retry_count < MAX_GENERATION_RETRIES:
                    retry_count += 1
                    retry_reasons.append(f"provider_error:{exc.code}:{exc.status_code}")
                    continue
                raise
            candidate = completion.text

            logic_validation = self._logic_validation(candidate)
            if not logic_validation["pass"]:
                last_validation = self._validation_result(
                    passed=False,
                    severity="hard",
                    error_codes=logic_validation["error_codes"],
                    rewrite_instruction=logic_validation["rewrite_instruction"],
                    fallback_recommended=logic_validation["fallback_recommended"],
                )
            else:
                last_validation = self._validator_llm(state=state, candidate_response_text=candidate)
                if last_validation["pass"]:
                    return Step11Result(
                        response_text=candidate,
                        metadata={
                            "generation_retry_count": retry_count,
                            "generation_retry_reasons": retry_reasons,
                            "validation_outcome": last_validation,
                            "fallback_used": False,
                        },
                    )

            retry_count += 1
            if retry_count <= MAX_GENERATION_RETRIES:
                retry_reasons.append(
                    "validation_failed"
                    if logic_validation["pass"]
                    else "logic_validation_failed"
                )
                prompt_messages = self._build_retry_prompt_messages(
                    base_prompt_messages=base_prompt_messages,
                    validation_result=last_validation,
                )
                continue

            raise LLMGatewayError(LLM_RESPONSE_GENERATION_FAILED, status_code=500)

    @staticmethod
    def _is_retryable_generation_error(error: LLMGatewayError) -> bool:
        if error.code in RETRYABLE_PROVIDER_ERROR_CODES:
            return True
        return error.status_code in RETRYABLE_PROVIDER_STATUS_CODES

    @staticmethod
    def _logic_validation(candidate_response_text: str) -> dict[str, Any]:
        text = candidate_response_text if isinstance(candidate_response_text, str) else ""
        if not text.strip():
            return {
                "pass": False,
                "error_codes": ["GENERAL_IRRELEVANT"],
                "rewrite_instruction": "Return a non-empty user-facing response.",
                "fallback_recommended": "ASK",
            }
        violations: list[str] = []
        if ResponseGenerationService._contains_harmful_instruction(text):
            violations.append("HARMFUL_INSTRUCTION")
        if ResponseGenerationService._contains_medical_advice(text):
            violations.append("MEDICAL_ADVICE_DISALLOWED")
        if ResponseGenerationService._contains_profanity(text):
            violations.append("UNSAFE_PROFANITY")
        if violations:
            return {
                "pass": False,
                "error_codes": violations,
                "rewrite_instruction": (
                    "Remove harmful/medical/profane content. Return supportive, safe, non-medical language "
                    "with no abusive wording."
                ),
                "fallback_recommended": "LISTEN",
            }
        return {"pass": True, "error_codes": [], "rewrite_instruction": "", "fallback_recommended": None}

    @staticmethod
    def _contains_medical_advice(text: str) -> bool:
        lower_text = text.lower()
        if not any(token in lower_text for token in ("thuốc", "liều", "medication", "medicine", "drug", "mg", "ml")):
            return False
        return any(pattern.search(text) is not None for pattern in MEDICAL_ADVICE_PATTERNS)

    @staticmethod
    def _contains_harmful_instruction(text: str) -> bool:
        lower_text = text.lower()
        if not any(
            token in lower_text
            for token in (
                "tự tử",
                "tự làm hại",
                "quá liều",
                "giết",
                "đánh",
                "đâm",
                "đốt",
                "kill",
                "hurt",
                "stab",
                "burn",
                "self-harm",
                "overdose",
            )
        ):
            return False
        return any(pattern.search(text) is not None for pattern in HARM_INSTRUCTION_PATTERNS)

    @staticmethod
    def _contains_profanity(text: str) -> bool:
        return any(pattern.search(text) is not None for pattern in PROFANITY_PATTERNS)

    @staticmethod
    def _build_retry_prompt_messages(
        *,
        base_prompt_messages: object,
        validation_result: dict[str, Any],
    ) -> list[dict[str, str]]:
        if not isinstance(base_prompt_messages, list):
            messages: list[dict[str, str]] = []
        else:
            messages = []
            for item in base_prompt_messages:
                if not isinstance(item, dict):
                    continue
                role = item.get("role")
                content = item.get("content")
                if isinstance(role, str) and isinstance(content, str) and role in {"system", "user", "assistant"}:
                    messages.append({"role": role, "content": content})

        error_codes = validation_result.get("error_codes")
        rewrite_instruction = validation_result.get("rewrite_instruction")
        fallback_recommended = validation_result.get("fallback_recommended")

        normalized_error_codes = ", ".join(error_codes) if isinstance(error_codes, list) and error_codes else "UNKNOWN"
        normalized_rewrite = (
            rewrite_instruction.strip()
            if isinstance(rewrite_instruction, str) and rewrite_instruction.strip()
            else "Revise response to satisfy validation constraints."
        )
        fallback_text = (
            fallback_recommended
            if isinstance(fallback_recommended, str) and fallback_recommended in {"ASK", "LISTEN"}
            else "none"
        )
        retry_constraints = (
            "Regeneration constraints from previous validation failure:\n"
            f"- Error codes: {normalized_error_codes}\n"
            f"- Required fixes: {normalized_rewrite}\n"
            f"- Preferred fallback mode: {fallback_text}\n"
            "Return one revised final response text only."
        )
        messages.append({"role": "user", "content": retry_constraints})
        return messages

    def _validator_llm(self, *, state, candidate_response_text: str) -> dict[str, Any]:
        effective_method_value = state.runtime_bundle.get("effective_response_method")
        if (
            isinstance(effective_method_value, str)
            and effective_method_value in {item.value for item in ResponseMethod}
        ):
            validation_method = ResponseMethod(effective_method_value)
        else:
            validation_method = state.response_method

        payload = {
            "candidate_response_text": candidate_response_text,
            "response_method": validation_method.value,
            "current_message": state.runtime_bundle.get("current_message", ""),
            "normalized_reasoning_result": state.normalized_reasoning_result,
        }
        if validation_method == ResponseMethod.TEACH:
            payload["retrieval_result"] = state.runtime_bundle.get("retrieval_result") or {}

        try:
            completion = self.llm_gateway.complete(
                operation_key=OperationKey.RESPONSE_VALIDATION,
                turn=state.turn,
                prompt_messages=[
                    {"role": "system", "content": RESPONSE_VALIDATION_SYSTEM},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            )
        except LLMGatewayError:
            # Fail-closed policy: do not downgrade validator provider failures into synthetic pass/fallback.
            raise

        parsed: dict[str, Any] = {}
        try:
            loaded = json.loads(completion.text)
            if isinstance(loaded, dict):
                parsed = loaded
        except (json.JSONDecodeError, TypeError):
            parsed = {}

        return self._validation_result(
            passed=bool(parsed.get("pass", False)),
            severity=parsed.get("severity"),
            error_codes=parsed.get("error_codes"),
            rewrite_instruction=parsed.get("rewrite_instruction"),
            fallback_recommended=parsed.get("fallback_recommended"),
        )

    @staticmethod
    def _validation_result(
        *,
        passed: bool,
        severity: object,
        error_codes: object,
        rewrite_instruction: object,
        fallback_recommended: object,
    ) -> dict[str, Any]:
        normalized_severity = "light" if severity == "light" else "hard"
        normalized_codes: list[str] = []
        if isinstance(error_codes, list):
            for item in error_codes:
                if isinstance(item, str) and item.strip() and item.strip() not in normalized_codes:
                    normalized_codes.append(item.strip())
        if not normalized_codes and not passed:
            normalized_codes = ["GENERAL_IRRELEVANT"]

        if isinstance(rewrite_instruction, str) and rewrite_instruction.strip():
            normalized_instruction = rewrite_instruction.strip()[:1200]
        elif passed:
            normalized_instruction = ""
        else:
            normalized_instruction = "Revise response to satisfy safety, relevance, and method constraints."

        normalized_fallback = None
        raw_fallback_recommended = None
        if isinstance(fallback_recommended, str):
            token = fallback_recommended.strip().upper()
            raw_fallback_recommended = token
            if token in {"ASK", "LISTEN"}:
                normalized_fallback = token

        return {
            "pass": bool(passed),
            "severity": normalized_severity,
            "error_codes": normalized_codes,
            "rewrite_instruction": normalized_instruction,
            "fallback_recommended": normalized_fallback,
            "raw_fallback_recommended": raw_fallback_recommended,
        }
