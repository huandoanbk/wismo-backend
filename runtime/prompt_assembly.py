"""Step 10 prompt assembly service for conversational response methods."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
from runtime.services import RuntimeConfigService
from wismo.contracts.enums import CONVERSATIONAL_RESPONSE_METHODS, ResponseMethod

MAX_PROMPT_ESTIMATED_TOKENS = 3500  # default; overridden per-call by RuntimeConfig runtime.prompt_assembly
MAX_RECENT_TURNS_WHEN_COMPACT = 2
MAX_RECENT_TURN_TEXT_CHARS = 180
MAX_CONTEXT_SUMMARY_CHARS_WHEN_COMPACT = 500
STEP10_RETRIEVAL_PREVIEW_MAX_CHARS = 400


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
        fallback_reason = ""
        if method == ResponseMethod.TEACH and not self._teach_retrieval_usable(data.get("retrieval_result")):
            effective_method = ResponseMethod.LISTEN
            fallback_reason = "teach_retrieval_unavailable"
        state.runtime_bundle["effective_response_method"] = effective_method.value
        if fallback_reason:
            state.runtime_bundle["effective_response_method_reason"] = fallback_reason
        else:
            state.runtime_bundle.pop("effective_response_method_reason", None)

        system_prompt, payload, used_fields = self._build_for_method(method=effective_method, data=data)
        compact_applied, payload = self._apply_compact_if_needed(
            method=effective_method,
            system_prompt=system_prompt,
            payload=payload,
        )
        prompt_messages = self._compose(system=system_prompt, payload=payload, method=effective_method)
        estimated_tokens = self._estimate_tokens(prompt_messages)
        retrieval_debug = self._build_retrieval_debug(
            effective_method=effective_method,
            retrieval_result=data.get("retrieval_result"),
        )

        return PromptAssemblyResult(
            prompt_messages=prompt_messages,
            prompt_debug_meta={
                "builder_name": self._builder_name(effective_method),
                "used_fields": sorted(set(used_fields)),
                "compact_applied": compact_applied,
                "estimated_tokens": estimated_tokens,
                **retrieval_debug,
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

    @staticmethod
    def _build_retrieval_debug(
        *,
        effective_method: ResponseMethod,
        retrieval_result: object,
    ) -> dict[str, object]:
        """Expose compact retrieval preview metadata in Step 10 traces."""

        retrieval_text = ""
        source_title = ""
        if isinstance(retrieval_result, dict):
            text = retrieval_result.get("retrieval_unit_text")
            if isinstance(text, str):
                retrieval_text = text.strip()
            payload = retrieval_result.get("retrieval_prompt_payload")
            if isinstance(payload, dict):
                payload_text = payload.get("content_text_for_prompt")
                if not retrieval_text and isinstance(payload_text, str):
                    retrieval_text = payload_text.strip()
                payload_source_title = payload.get("source_title")
                if isinstance(payload_source_title, str):
                    source_title = payload_source_title.strip()
        preview = PromptAssemblyService._preview_text(retrieval_text, STEP10_RETRIEVAL_PREVIEW_MAX_CHARS)
        return {
            "retrieval_included": effective_method == ResponseMethod.TEACH and bool(retrieval_text),
            "retrieval_unit_chars": len(retrieval_text),
            "retrieval_unit_preview": preview,
            "retrieval_source_title": source_title,
        }

    @staticmethod
    def _preview_text(text: str, max_chars: int) -> str:
        """Return a bounded one-line preview string."""

        normalized = " ".join(text.split())
        if len(normalized) <= max_chars:
            return normalized
        return f"{normalized[:max_chars]}...[truncated]"

    def _normalized_inputs(self, state) -> dict[str, Any]:
        bundle = state.runtime_bundle if isinstance(state.runtime_bundle, dict) else {}
        reasoning = state.normalized_reasoning_result if isinstance(state.normalized_reasoning_result, dict) else {}

        return {
            "current_message": self._as_text(bundle.get("current_message") or getattr(state.request_payload, "message", "")),
            "recent_turns": self._as_recent_turns(bundle.get("recent_turns")),
            "context_summary": self._as_text(bundle.get("context_summary")),
            "style_signals": self._as_string_list(
                reasoning.get("style_signals_next") or reasoning.get("style_signals")
            ),
            "user_state_signals": self._as_string_list(
                reasoning.get("user_state_signals_next") or reasoning.get("user_state_signals")
            ),
            "explicit_profile_facts": self._as_string_list(
                reasoning.get("explicit_profile_facts_next") or reasoning.get("explicit_profile_facts")
            ),
            "required_next_slots": self._as_string_list(reasoning.get("required_next_slots")),
            "case_slots": self._as_str_dict(reasoning.get("case_slots")),
            "intent": self._as_text(reasoning.get("intent")),
            "turn_strategy": self._as_turn_strategy(reasoning.get("turn_strategy")),
            "retrieval_result": reasoning.get("retrieval_result") or bundle.get("retrieval_result"),
            "long_term_memory_segments": self._latest_three_long_term_segments(
                self._as_long_term_memory_segments(bundle.get("long_term_memory"))
            ),
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
    def _as_long_term_memory_segments(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, object]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            open_loops = item.get("open_loops")
            normalized.append(
                {
                    "user_concern_summary": item.get("user_concern_summary", "") if isinstance(item.get("user_concern_summary"), str) else "",
                    "assistant_approach_summary": item.get("assistant_approach_summary", "") if isinstance(item.get("assistant_approach_summary"), str) else "",
                    "user_response_summary": item.get("user_response_summary", "") if isinstance(item.get("user_response_summary"), str) else "",
                    "state_shift": item.get("state_shift", "") if isinstance(item.get("state_shift"), str) else "",
                    "open_loops": [x.strip() for x in open_loops if isinstance(x, str) and x.strip()]
                    if isinstance(open_loops, list)
                    else [],
                    "updated_at": item.get("updated_at", "") if isinstance(item.get("updated_at"), str) else "",
                }
            )
        return normalized

    @staticmethod
    def _latest_three_long_term_segments(value: list[dict[str, object]]) -> list[dict[str, object]]:
        if not value:
            return []

        def _parse_dt(raw: object) -> datetime:
            if not isinstance(raw, str) or not raw.strip():
                return datetime.min
            text = raw.strip().replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(text)
            except ValueError:
                return datetime.min

        with_index = list(enumerate(value))
        with_index.sort(key=lambda pair: (_parse_dt(pair[1].get("updated_at")), pair[0]), reverse=True)
        return [item for _idx, item in with_index[:3]]

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

    def _build_for_method(
        self,
        *,
        method: ResponseMethod,
        data: dict[str, Any],
    ) -> tuple[str, dict[str, Any], list[str]]:
        if method == ResponseMethod.LISTEN:
            return self._build_listen_prompt(data)
        if method == ResponseMethod.ASK:
            return self._build_ask_prompt(data)
        if method == ResponseMethod.REFLECT:
            return self._build_reflect_prompt(data)
        if method == ResponseMethod.FOLLOWUP:
            return self._build_followup_prompt(data)
        return self._build_teach_prompt(data)

    def _build_listen_prompt(self, data: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
        used_fields = [
            "current_message",
            "context_summary",
            "recent_turns",
            "style_signals",
            "user_state_signals",
            "explicit_profile_facts",
            "long_term_memory",
        ]
        payload = {
            "current_message": data["current_message"],
            "context_summary": data["context_summary"],
            "recent_turns": data["recent_turns"],
            "style_signals": data["style_signals"] or ["neutral_gentle_brief"],
            "user_state_signals": data["user_state_signals"] or ["neutral"],
            "explicit_profile_facts": data["explicit_profile_facts"],
            "long_term_memory_segments": data["long_term_memory_segments"],
        }
        return self._system_with_instruction(LISTEN_SYSTEM, LISTEN_INSTRUCTION), payload, used_fields

    def _build_ask_prompt(self, data: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
        used_fields = [
            "current_message",
            "context_summary",
            "required_next_slots",
            "case_slots",
            "style_signals",
            "user_state_signals",
            "explicit_profile_facts",
            "long_term_memory",
        ]
        payload = {
            "current_message": data["current_message"],
            "required_next_slots": data["required_next_slots"],
            "case_slots": data["case_slots"],
            "context_summary": data["context_summary"],
            "style_signals": data["style_signals"] or ["neutral_gentle_brief"],
            "user_state_signals": data["user_state_signals"] or ["neutral"],
            "explicit_profile_facts": data["explicit_profile_facts"],
            "long_term_memory_segments": data["long_term_memory_segments"],
        }
        return self._system_with_instruction(ASK_SYSTEM, ASK_INSTRUCTION), payload, used_fields

    def _build_reflect_prompt(self, data: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
        used_fields = [
            "current_message",
            "context_summary",
            "intent",
            "case_slots",
            "style_signals",
            "user_state_signals",
            "explicit_profile_facts",
            "long_term_memory",
        ]

        payload = {
            "current_message": data["current_message"],
            "context_summary": data["context_summary"],
            "case_slots": data["case_slots"],
            "intent": data["intent"],
            "style_signals": data["style_signals"] or ["neutral_gentle_brief"],
            "user_state_signals": data["user_state_signals"] or ["neutral"],
            "explicit_profile_facts": data["explicit_profile_facts"],
            "long_term_memory_segments": data["long_term_memory_segments"],
        }
        return self._system_with_instruction(REFLECT_SYSTEM, REFLECT_INSTRUCTION), payload, used_fields

    def _build_followup_prompt(self, data: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
        used_fields = [
            "current_message",
            "context_summary",
            "recent_turns",
            "turn_strategy",
            "case_slots",
            "style_signals",
            "user_state_signals",
            "explicit_profile_facts",
            "long_term_memory",
        ]

        payload = {
            "current_message": data["current_message"],
            "context_summary": data["context_summary"],
            "turn_strategy": data["turn_strategy"],
            "case_slots": data["case_slots"],
            "recent_turns": data["recent_turns"],
            "style_signals": data["style_signals"] or ["neutral_gentle_brief"],
            "user_state_signals": data["user_state_signals"] or ["neutral"],
            "explicit_profile_facts": data["explicit_profile_facts"],
            "long_term_memory_segments": data["long_term_memory_segments"],
        }
        return self._system_with_instruction(FOLLOWUP_SYSTEM, FOLLOWUP_INSTRUCTION), payload, used_fields

    def _build_teach_prompt(self, data: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
        used_fields = [
            "current_message",
            "context_summary",
            "turn_strategy",
            "retrieval_result",
            "style_signals",
            "user_state_signals",
            "explicit_profile_facts",
            "long_term_memory",
        ]

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
            "style_signals": data["style_signals"] or ["neutral_gentle_brief"],
            "user_state_signals": data["user_state_signals"] or ["neutral"],
            "explicit_profile_facts": data["explicit_profile_facts"],
            "long_term_memory_segments": data["long_term_memory_segments"],
        }
        return self._system_with_instruction(TEACH_SYSTEM, TEACH_INSTRUCTION), payload, used_fields

    @staticmethod
    def _system_with_instruction(system: str, instruction: str) -> str:
        return f"{system}\nTask: {instruction}"

    def _compose(self, *, system: str, payload: dict[str, Any], method: ResponseMethod) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": self._render_user_content(payload=payload, method=method)},
        ]

    def _render_user_content(self, *, payload: dict[str, Any], method: ResponseMethod) -> str:
        if method == ResponseMethod.LISTEN:
            return self._render_listen_user_content(payload)
        if method == ResponseMethod.ASK:
            return self._render_ask_user_content(payload)
        if method == ResponseMethod.REFLECT:
            return self._render_reflect_user_content(payload)
        if method == ResponseMethod.FOLLOWUP:
            return self._render_followup_user_content(payload)
        return self._render_teach_user_content(payload)

    def _render_listen_user_content(self, payload: dict[str, Any]) -> str:
        lines = self._base_lines(payload, include_recent_turns=True)
        self._append_long_term_memory(lines, payload)
        return "\n".join(lines)

    def _render_ask_user_content(self, payload: dict[str, Any]) -> str:
        lines = self._base_lines(payload)
        self._append_missing_slots(lines, payload)
        self._append_case_slots(lines, payload)
        self._append_long_term_memory(lines, payload)
        return "\n".join(lines)

    def _render_reflect_user_content(self, payload: dict[str, Any]) -> str:
        lines = self._base_lines(payload)
        self._append_intent(lines, payload)
        self._append_case_slots(lines, payload)
        self._append_long_term_memory(lines, payload)
        return "\n".join(lines)

    def _render_followup_user_content(self, payload: dict[str, Any]) -> str:
        lines = self._base_lines(payload, include_recent_turns=True)
        self._append_case_slots(lines, payload)
        self._append_turn_strategy(lines, payload)
        self._append_long_term_memory(lines, payload)
        return "\n".join(lines)

    def _render_teach_user_content(self, payload: dict[str, Any]) -> str:
        lines = self._base_lines(payload)
        self._append_turn_strategy(lines, payload)
        self._append_knowledge_unit(lines, payload)
        self._append_long_term_memory(lines, payload)
        return "\n".join(lines)

    def _base_lines(self, payload: dict[str, Any], *, include_recent_turns: bool = False) -> list[str]:
        lines: list[str] = []
        current_message = payload.get("current_message")
        lines.append(f"- Current message: {current_message}" if isinstance(current_message, str) and current_message else "- Current message: none")

        context_summary = payload.get("context_summary")
        if isinstance(context_summary, str) and context_summary:
            lines.append(f"- Context summary: {context_summary}")

        if include_recent_turns:
            self._append_recent_turns(lines, payload)

        self._append_style_signals(lines, payload)
        self._append_user_state_signals(lines, payload)
        self._append_profile_facts(lines, payload)
        return lines

    @staticmethod
    def _append_recent_turns(lines: list[str], payload: dict[str, Any]) -> None:
        recent_turns = payload.get("recent_turns")
        if not isinstance(recent_turns, list) or not recent_turns:
            return
        lines.append("- Recent turns:")
        for index, item in enumerate(recent_turns, start=1):
            if not isinstance(item, dict):
                continue
            user_message = item.get("user_message") if isinstance(item.get("user_message"), str) else ""
            assistant_response = item.get("assistant_response") if isinstance(item.get("assistant_response"), str) else ""
            if user_message or assistant_response:
                lines.append(f"  {index}. User: {user_message}")
                lines.append(f"     Assistant: {assistant_response}")

    @staticmethod
    def _append_style_signals(lines: list[str], payload: dict[str, Any]) -> None:
        style_signals = payload.get("style_signals")
        if not isinstance(style_signals, list) or not style_signals:
            return
        values = [item for item in style_signals if isinstance(item, str) and item]
        if values:
            lines.append(f"- Style signals: {', '.join(values)}")

    @staticmethod
    def _append_user_state_signals(lines: list[str], payload: dict[str, Any]) -> None:
        user_state_signals = payload.get("user_state_signals")
        if not isinstance(user_state_signals, list) or not user_state_signals:
            return
        values = [item for item in user_state_signals if isinstance(item, str) and item]
        if values:
            lines.append(f"- User state signals: {', '.join(values)}")

    @staticmethod
    def _append_profile_facts(lines: list[str], payload: dict[str, Any]) -> None:
        explicit_profile_facts = payload.get("explicit_profile_facts")
        if not isinstance(explicit_profile_facts, list) or not explicit_profile_facts:
            return
        values = [item for item in explicit_profile_facts if isinstance(item, str) and item]
        if values:
            lines.append("- Profile facts:")
            for item in values:
                lines.append(f"  - {item}")

    @staticmethod
    def _append_missing_slots(lines: list[str], payload: dict[str, Any]) -> None:
        required_slots = payload.get("required_next_slots")
        if not isinstance(required_slots, list) or not required_slots:
            return
        lines.append(f"- Missing slots to ask: {', '.join(required_slots)}")

    @staticmethod
    def _append_case_slots(lines: list[str], payload: dict[str, Any]) -> None:
        case_slots = payload.get("case_slots")
        if not isinstance(case_slots, dict) or not case_slots:
            return
        slot_pairs = [f"{key}: {value}" for key, value in case_slots.items() if isinstance(value, str) and value]
        if slot_pairs:
            lines.append("- Known case slots:")
            for pair in slot_pairs:
                lines.append(f"  - {pair}")

    @staticmethod
    def _append_intent(lines: list[str], payload: dict[str, Any]) -> None:
        intent = payload.get("intent")
        if isinstance(intent, str) and intent:
            lines.append(f"- Intent: {intent}")

    @staticmethod
    def _append_turn_strategy(lines: list[str], payload: dict[str, Any]) -> None:
        turn_strategy = payload.get("turn_strategy")
        if not isinstance(turn_strategy, dict) or not turn_strategy:
            return
        focus = turn_strategy.get("focus") if isinstance(turn_strategy.get("focus"), str) else ""
        angle = turn_strategy.get("angle") if isinstance(turn_strategy.get("angle"), str) else ""
        avoid = turn_strategy.get("avoid") if isinstance(turn_strategy.get("avoid"), list) else []
        avoid_values = [item for item in avoid if isinstance(item, str) and item]
        strategy_parts: list[str] = []
        if focus:
            strategy_parts.append(f"focus={focus}")
        if angle:
            strategy_parts.append(f"angle={angle}")
        if avoid_values:
            strategy_parts.append(f"avoid={'; '.join(avoid_values)}")
        if strategy_parts:
            lines.append(f"- Turn strategy: {'; '.join(strategy_parts)}")

    @staticmethod
    def _append_knowledge_unit(lines: list[str], payload: dict[str, Any]) -> None:
        retrieval_unit_text = payload.get("retrieval_unit_text")
        if isinstance(retrieval_unit_text, str) and retrieval_unit_text:
            lines.append("- Knowledge unit:")
            lines.append(retrieval_unit_text)
        retrieval_prompt_payload = payload.get("retrieval_prompt_payload")
        if isinstance(retrieval_prompt_payload, dict):
            source_title = retrieval_prompt_payload.get("source_title")
            if isinstance(source_title, str) and source_title:
                lines.append(f"- Source title (internal): {source_title}")

    @staticmethod
    def _append_long_term_memory(lines: list[str], payload: dict[str, Any]) -> None:
        segments = payload.get("long_term_memory_segments")
        if not isinstance(segments, list) or not segments:
            lines.append("- Long-term memory (latest 3 segments): none")
            return

        lines.append("- Long-term memory (latest 3 segments):")
        for index, segment in enumerate(segments[:3], start=1):
            if not isinstance(segment, dict):
                continue
            user_concern = segment.get("user_concern_summary") if isinstance(segment.get("user_concern_summary"), str) else ""
            assistant_approach = segment.get("assistant_approach_summary") if isinstance(segment.get("assistant_approach_summary"), str) else ""
            user_response = segment.get("user_response_summary") if isinstance(segment.get("user_response_summary"), str) else ""
            state_shift = segment.get("state_shift") if isinstance(segment.get("state_shift"), str) else ""
            open_loops = segment.get("open_loops") if isinstance(segment.get("open_loops"), list) else []
            loop_values = [item for item in open_loops if isinstance(item, str) and item]

            lines.append(f"  {index}. User concern: {user_concern or 'none'}")
            lines.append(f"     Assistant approach: {assistant_approach or 'none'}")
            lines.append(f"     User response: {user_response or 'none'}")
            lines.append(f"     State shift: {state_shift or 'none'}")
            lines.append(f"     Open loops: {'; '.join(loop_values) if loop_values else 'none'}")

    def _apply_compact_if_needed(
        self,
        *,
        method: ResponseMethod,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        max_tokens = RuntimeConfigService().prompt_assembly_policy().max_estimated_tokens
        estimated = self._estimate_tokens(self._compose(system=system_prompt, payload=payload, method=method))
        if estimated <= max_tokens:
            return False, payload

        changed = False
        recent_turns = payload.get("recent_turns")
        if isinstance(recent_turns, list):
            compacted_turns = self._compact_recent_turns(recent_turns)
            if compacted_turns != recent_turns:
                payload["recent_turns"] = compacted_turns
                changed = True

        if self._estimate_tokens(self._compose(system=system_prompt, payload=payload, method=method)) > max_tokens:
            text = payload.get("context_summary")
            if isinstance(text, str) and text:
                compacted_summary = text[:MAX_CONTEXT_SUMMARY_CHARS_WHEN_COMPACT]
                if compacted_summary != text:
                    payload["context_summary"] = compacted_summary
                    changed = True

        if method == ResponseMethod.TEACH:
            if self._estimate_tokens(self._compose(system=system_prompt, payload=payload, method=method)) > max_tokens:
                if isinstance(payload.get("turn_strategy"), dict) and payload.get("turn_strategy"):
                    payload["turn_strategy"] = {}
                    changed = True
            if self._estimate_tokens(self._compose(system=system_prompt, payload=payload, method=method)) > max_tokens:
                if isinstance(payload.get("context_summary"), str) and payload.get("context_summary"):
                    payload["context_summary"] = ""
                    changed = True
            if self._estimate_tokens(self._compose(system=system_prompt, payload=payload, method=method)) > max_tokens:
                retrieval_payload = payload.get("retrieval_prompt_payload")
                if isinstance(retrieval_payload, dict) and retrieval_payload:
                    payload["retrieval_prompt_payload"] = {}
                    changed = True

        return changed, payload

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
