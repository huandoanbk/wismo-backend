"""Step 11 response generation, validation, retry, and fallback service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from llm_ops.errors import LLM_RESPONSE_GENERATION_FAILED, LLMGatewayError
from llm_ops.gateway import LLMGateway
from runtime.prompts import RESPONSE_VALIDATION_SYSTEM
from wismo.contracts.enums import OperationKey, ResponseMethod

MAX_GENERATION_RETRIES = 2


@dataclass(frozen=True)
class Step11Result:
    """Canonical Step 11 outcome."""

    response_text: str
    metadata: dict[str, Any]


class ResponseGenerationService:
    """Execute Step 11 lifecycle using Main Flow/MVP contracts."""

    def __init__(self, llm_gateway: LLMGateway) -> None:
        self.llm_gateway = llm_gateway

    def run(self, *, state, rebuild_prompt) -> Step11Result:
        """Generate, validate, retry, and return final response text with trace metadata."""

        retry_count = 0
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
                    prompt_messages=state.runtime_bundle.get("prompt_messages", []),
                )
            except LLMGatewayError:
                # Fail-closed policy: surface provider/runtime errors to orchestrator error path.
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
                            "validation_outcome": last_validation,
                            "fallback_used": False,
                        },
                    )

            retry_count += 1
            if retry_count <= MAX_GENERATION_RETRIES:
                state.runtime_bundle["generation_validation_feedback"] = {
                    "error_codes": last_validation["error_codes"],
                    "rewrite_instruction": last_validation["rewrite_instruction"],
                    "keep_constraints": ["response_method", "final_safety_state"],
                }
                rebuild_prompt(state)
                continue

            raise LLMGatewayError(LLM_RESPONSE_GENERATION_FAILED, status_code=500)

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
        return {"pass": True, "error_codes": [], "rewrite_instruction": "", "fallback_recommended": None}

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
            "final_safety_state": state.final_safety_state,
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

