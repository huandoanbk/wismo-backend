"""Step 10 prompt assembly service for conversational response methods."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from runtime.prompts import (
    ASK_INSTRUCTION,
    ASK_SYSTEM,
    FOLLOWUP_INSTRUCTION,
    FOLLOWUP_SYSTEM,
    LISTEN_INSTRUCTION,
    LISTEN_SYSTEM,
    REFLECT_INSTRUCTION,
    REFLECT_SYSTEM,
    TEACH_INSTRUCTION,
    TEACH_SYSTEM,
)
from wismo.contracts.enums import CONVERSATIONAL_RESPONSE_METHODS, ResponseMethod

MAX_PROMPT_ESTIMATED_TOKENS = 2200
MAX_RECENT_TURNS_WHEN_COMPACT = 2
MAX_RECENT_TURN_TEXT_CHARS = 180
MAX_CONTEXT_SUMMARY_CHARS_WHEN_COMPACT = 500


@dataclass(frozen=True)
class PromptAssemblyResult:
    """Canonical Step 10 output payload."""

    prompt_messages: list[dict[str, str]]
    prompt_debug_meta: dict[str, Any]


class PromptAssemblyService:
    """Build Step 10 prompt messages from runtime state without DB reads."""

    def build(self, *, state) -> PromptAssemblyResult:
        """Assemble prompt messages and debug metadata for the current conversational method."""

        method = state.response_method
        if method not in CONVERSATIONAL_RESPONSE_METHODS:
            raise RuntimeError("step10_non_conversational_method")

        effective_method = method

        data = self._normalized_inputs(state)
        if method == ResponseMethod.TEACH and not self._teach_retrieval_usable(data.get("retrieval_result")):
            effective_method = ResponseMethod.LISTEN
        state.runtime_bundle["effective_response_method"] = effective_method.value

        prompt_messages, used_fields = self._build_for_method(method=effective_method, data=data)
        prompt_messages = self._apply_generation_feedback(messages=prompt_messages, data=data)
        compact_applied, prompt_messages = self._apply_compact_if_needed(method=effective_method, messages=prompt_messages)
        estimated_tokens = self._estimate_tokens(prompt_messages)

        return PromptAssemblyResult(
            prompt_messages=prompt_messages,
            prompt_debug_meta={
                "builder_name": self._builder_name(effective_method),
                "used_fields": sorted(set(used_fields)),
                "compact_applied": compact_applied,
                "estimated_tokens": estimated_tokens,
            },
        )

    @staticmethod
    def _builder_name(method: ResponseMethod) -> str:
        mapping = {
            ResponseMethod.LISTEN: "build_listen_prompt",
            ResponseMethod.ASK: "build_ask_prompt",
            ResponseMethod.REFLECT: "build_reflect_prompt",
            ResponseMethod.FOLLOWUP: "build_followup_prompt",
            ResponseMethod.TEACH: "build_teach_prompt",
        }
        return mapping[method]

    def _normalized_inputs(self, state) -> dict[str, Any]:
        bundle = state.runtime_bundle if isinstance(state.runtime_bundle, dict) else {}
        reasoning = state.normalized_reasoning_result if isinstance(state.normalized_reasoning_result, dict) else {}

        return {
            "current_message": self._as_text(bundle.get("current_message") or getattr(state.request_payload, "message", "")),
            "recent_turns": self._as_recent_turns(bundle.get("recent_turns")),
            "context_summary": self._as_text(bundle.get("context_summary")),
            "style_signals": self._as_string_list(reasoning.get("style_signals")),
            "user_state_signals": self._as_string_list(reasoning.get("user_state_signals")),
            "required_next_slots": self._as_string_list(reasoning.get("required_next_slots")),
            "case_slots": self._as_str_dict(reasoning.get("case_slots")),
            "intent": self._as_text(reasoning.get("intent")),
            "turn_strategy": self._as_turn_strategy(reasoning.get("turn_strategy")),
            "retrieval_result": reasoning.get("retrieval_result") or bundle.get("retrieval_result"),
            "generation_validation_feedback": self._as_generation_feedback(bundle.get("generation_validation_feedback")),
        }

    @staticmethod
    def _as_text(value: object) -> str:
        if isinstance(value, str):
            return value.strip()
        return ""

    @staticmethod
    def _as_string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        values: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                values.append(item.strip())
        return values

    def _as_recent_turns(self, value: object) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            user_text = self._as_text(item.get("user_message_text") or item.get("user_message"))
            assistant_text = self._as_text(item.get("assistant_response_text") or item.get("assistant_response"))
            if not user_text and not assistant_text:
                continue
            normalized.append({"user_message": user_text, "assistant_response": assistant_text})
        return normalized

    @staticmethod
    def _as_str_dict(value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, str] = {}
        for key, candidate in value.items():
            if isinstance(key, str) and isinstance(candidate, str) and candidate.strip():
                normalized[key] = candidate.strip()
        return normalized

    @staticmethod
    def _as_turn_strategy(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, object] = {}
        focus = value.get("focus")
        angle = value.get("angle")
        avoid = value.get("avoid")
        if isinstance(focus, str) and focus.strip():
            result["focus"] = focus.strip()
        if isinstance(angle, str) and angle.strip():
            result["angle"] = angle.strip()
        if isinstance(avoid, list):
            cleaned = [item.strip() for item in avoid if isinstance(item, str) and item.strip()]
            if cleaned:
                result["avoid"] = cleaned
        return result

    @staticmethod
    def _as_generation_feedback(value: object) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        error_codes = value.get("error_codes")
        rewrite = value.get("rewrite_instruction")
        keep_constraints = value.get("keep_constraints")
        normalized_codes: list[str] = []
        if isinstance(error_codes, list):
            normalized_codes = [item.strip() for item in error_codes if isinstance(item, str) and item.strip()][:20]
        normalized: dict[str, object] = {}
        if normalized_codes:
            normalized["error_codes"] = normalized_codes
        if isinstance(rewrite, str) and rewrite.strip():
            normalized["rewrite_instruction"] = rewrite.strip()[:1200]
        if isinstance(keep_constraints, list):
            normalized["keep_constraints"] = [
                item.strip() for item in keep_constraints if isinstance(item, str) and item.strip()
            ][:20]
        elif isinstance(keep_constraints, bool):
            normalized["keep_constraints"] = keep_constraints
        return normalized or None

    @staticmethod
    def _teach_retrieval_usable(retrieval_result: object) -> bool:
        if not isinstance(retrieval_result, dict):
            return False
        text = retrieval_result.get("retrieval_unit_text")
        if isinstance(text, str) and text.strip():
            return True
        payload = retrieval_result.get("retrieval_prompt_payload")
        if isinstance(payload, dict):
            prompt_text = payload.get("content_text_for_prompt")
            if isinstance(prompt_text, str) and prompt_text.strip():
                return True
        return False

    def _build_for_method(self, *, method: ResponseMethod, data: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
        if method == ResponseMethod.LISTEN:
            return self._build_listen_prompt(data)
        if method == ResponseMethod.ASK:
            return self._build_ask_prompt(data)
        if method == ResponseMethod.REFLECT:
            return self._build_reflect_prompt(data)
        if method == ResponseMethod.FOLLOWUP:
            return self._build_followup_prompt(data)
        return self._build_teach_prompt(data)

    def _build_listen_prompt(self, data: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
        used_fields = ["current_message", "style_signals", "user_state_signals"]
        if data["context_summary"]:
            used_fields.append("context_summary")
        if data["recent_turns"]:
            used_fields.append("recent_turns")

        payload = {
            "current_message": data["current_message"],
            "context_summary": data["context_summary"],
            "style_signals": data["style_signals"] or ["neutral_gentle_brief"],
            "user_state_signals": data["user_state_signals"] or ["neutral"],
            "instruction": LISTEN_INSTRUCTION,
        }
        return self._compose(system=LISTEN_SYSTEM, payload=payload), used_fields

    def _build_ask_prompt(self, data: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
        used_fields = ["current_message", "required_next_slots", "case_slots", "style_signals"]
        if data["context_summary"]:
            used_fields.append("context_summary")

        payload = {
            "current_message": data["current_message"],
            "required_next_slots": data["required_next_slots"],
            "case_slots": data["case_slots"],
            "context_summary": data["context_summary"],
            "instruction": ASK_INSTRUCTION,
        }
        return self._compose(system=ASK_SYSTEM, payload=payload), used_fields

    def _build_reflect_prompt(self, data: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
        used_fields = ["current_message", "style_signals", "user_state_signals"]
        if data["context_summary"]:
            used_fields.append("context_summary")
        if data["case_slots"]:
            used_fields.append("case_slots")
        if data["intent"]:
            used_fields.append("intent")

        payload = {
            "current_message": data["current_message"],
            "context_summary": data["context_summary"],
            "case_slots": data["case_slots"],
            "intent": data["intent"],
            "style_signals": data["style_signals"],
            "user_state_signals": data["user_state_signals"],
            "instruction": REFLECT_INSTRUCTION,
        }
        return self._compose(system=REFLECT_SYSTEM, payload=payload), used_fields

    def _build_followup_prompt(self, data: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
        used_fields = ["current_message", "case_slots", "style_signals", "user_state_signals"]
        if data["context_summary"]:
            used_fields.append("context_summary")
        if data["turn_strategy"]:
            used_fields.append("turn_strategy")
        if data["recent_turns"]:
            used_fields.append("recent_turns")

        payload = {
            "current_message": data["current_message"],
            "context_summary": data["context_summary"],
            "turn_strategy": data["turn_strategy"],
            "case_slots": data["case_slots"],
            "recent_turns": data["recent_turns"],
            "style_signals": data["style_signals"],
            "user_state_signals": data["user_state_signals"],
            "instruction": FOLLOWUP_INSTRUCTION,
        }
        return self._compose(system=FOLLOWUP_SYSTEM, payload=payload), used_fields

    def _build_teach_prompt(self, data: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
        used_fields = ["current_message", "style_signals", "user_state_signals", "retrieval_result"]
        if data["context_summary"]:
            used_fields.append("context_summary")
        if data["turn_strategy"]:
            used_fields.append("turn_strategy")

        retrieval_result = data.get("retrieval_result") if isinstance(data.get("retrieval_result"), dict) else {}
        prompt_payload = retrieval_result.get("retrieval_prompt_payload") if isinstance(retrieval_result, dict) else {}
        retrieval_text = ""
        if isinstance(retrieval_result.get("retrieval_unit_text"), str):
            retrieval_text = retrieval_result["retrieval_unit_text"].strip()
        if not retrieval_text and isinstance(prompt_payload, dict):
            alt = prompt_payload.get("content_text_for_prompt")
            if isinstance(alt, str):
                retrieval_text = alt.strip()

        payload = {
            "current_message": data["current_message"],
            "context_summary": data["context_summary"],
            "turn_strategy": data["turn_strategy"],
            "retrieval_unit_text": retrieval_text,
            "retrieval_prompt_payload": prompt_payload if isinstance(prompt_payload, dict) else {},
            "style_signals": data["style_signals"],
            "user_state_signals": data["user_state_signals"],
            "instruction": TEACH_INSTRUCTION,
        }
        return self._compose(system=TEACH_SYSTEM, payload=payload), used_fields

    @staticmethod
    def _compose(*, system: str, payload: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

    @staticmethod
    def _apply_generation_feedback(*, messages: list[dict[str, str]], data: dict[str, Any]) -> list[dict[str, str]]:
        feedback = data.get("generation_validation_feedback")
        if not isinstance(feedback, dict):
            return messages
        try:
            payload = json.loads(messages[1]["content"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return messages
        if not isinstance(payload, dict):
            return messages
        payload["generation_validation_feedback"] = feedback
        return [messages[0], {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]

    def _apply_compact_if_needed(
        self,
        *,
        method: ResponseMethod,
        messages: list[dict[str, str]],
    ) -> tuple[bool, list[dict[str, str]]]:
        estimated = self._estimate_tokens(messages)
        if estimated <= MAX_PROMPT_ESTIMATED_TOKENS:
            return False, messages

        try:
            payload = json.loads(messages[1]["content"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return False, messages
        if not isinstance(payload, dict):
            return False, messages

        changed = False
        if isinstance(payload.get("recent_turns"), list):
            compacted_turns = self._compact_recent_turns(payload["recent_turns"])
            if compacted_turns != payload["recent_turns"]:
                payload["recent_turns"] = compacted_turns
                changed = True

        candidate = [messages[0], {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        if self._estimate_tokens(candidate) > MAX_PROMPT_ESTIMATED_TOKENS:
            text = payload.get("context_summary")
            if isinstance(text, str) and text:
                compacted_summary = text[:MAX_CONTEXT_SUMMARY_CHARS_WHEN_COMPACT]
                if compacted_summary != text:
                    payload["context_summary"] = compacted_summary
                    changed = True

        if method == ResponseMethod.TEACH:
            # For TEACH we preserve retrieval unit text and compact secondary context first.
            if self._estimate_tokens([messages[0], {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]) > MAX_PROMPT_ESTIMATED_TOKENS:
                if isinstance(payload.get("turn_strategy"), dict) and payload.get("turn_strategy"):
                    payload["turn_strategy"] = {}
                    changed = True
            if self._estimate_tokens([messages[0], {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]) > MAX_PROMPT_ESTIMATED_TOKENS:
                if isinstance(payload.get("context_summary"), str) and payload.get("context_summary"):
                    payload["context_summary"] = ""
                    changed = True
            if self._estimate_tokens([messages[0], {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]) > MAX_PROMPT_ESTIMATED_TOKENS:
                retrieval_payload = payload.get("retrieval_prompt_payload")
                if isinstance(retrieval_payload, dict) and retrieval_payload:
                    payload["retrieval_prompt_payload"] = {}
                    changed = True

        final_messages = [messages[0], {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        return changed, final_messages

    @staticmethod
    def _compact_recent_turns(value: list[object]) -> list[dict[str, str]]:
        compacted: list[dict[str, str]] = []
        for item in value[-MAX_RECENT_TURNS_WHEN_COMPACT:]:
            if not isinstance(item, dict):
                continue
            user_text = item.get("user_message")
            assistant_text = item.get("assistant_response")
            compacted.append(
                {
                    "user_message": user_text[:MAX_RECENT_TURN_TEXT_CHARS] if isinstance(user_text, str) else "",
                    "assistant_response": (
                        assistant_text[:MAX_RECENT_TURN_TEXT_CHARS] if isinstance(assistant_text, str) else ""
                    ),
                }
            )
        return compacted

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, str]]) -> int:
        text = " ".join(message.get("content", "") for message in messages if isinstance(message, dict))
        return max(1, len(text) // 4)
