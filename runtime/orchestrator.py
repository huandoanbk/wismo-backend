"""MVP runtime orchestrator with SSE generator pattern."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from chat.models import ChatTurn
from chat.services import CHAT_DISPLAY_NAME_FALLBACK, ChatContextService
from llm_ops.errors import (
    LLM_GATEWAY_PROVIDER_ERROR,
    LLM_GATEWAY_PROVIDER_UNAVAILABLE,
    LLMGatewayError,
)
from llm_ops.gateway import LLMGateway
from runtime.embedding import EmbeddingService
from runtime.finalization import PostTurnFinalizationService
from runtime.prompt_assembly import PromptAssemblyService
from runtime.prompts import FULL_REASONING_SYSTEM
from runtime.request_gate import GateResult, RequestGatePipeline
from runtime.reranker import RerankerClient
from runtime.response_generation import ResponseGenerationService
from runtime.retrieval import KnowledgeRetrievalService
from runtime.services import QuotaService, RuntimeBundleService, RuntimeConfigService
from runtime.triage import ControlResponse, FastTriageService, TriageResult
from wismo.contracts.enums import (
    CONVERSATIONAL_RESPONSE_METHODS,
    OperationKey,
    ResponseMethod,
    Step12FinalizationStatus,
    TriageDecision,
    TurnStatus,
    UsageAccountingStatus,
)

logger = logging.getLogger(__name__)

MAX_REASONING_GATEWAY_RETRIES = 2
MAX_REASONING_CORRECTIVE_RETRIES = 2
TRANSIENT_REASONING_ERROR_CODES = {
    LLM_GATEWAY_PROVIDER_ERROR,
    LLM_GATEWAY_PROVIDER_UNAVAILABLE,
}
RISK_FLAG_VALUES = {
    "crisis_self_harm",
    "crisis_harm_others",
    "minor_age_block",
    "medical_out_of_scope",
    "legal_out_of_scope",
    "policy_bypass",
    "spam_or_nonsense",
    "none",
}
INTENT_VALUES = {
    "emotional_support",
    "self_understanding",
    "ask_how_to_respond",
    "ask_what_to_do",
    "ask_teaching_or_perspective",
    "report_progress",
    "continue_previous_topic",
    "unclear",
}
REQUIRED_NEXT_SLOT_VALUES = {
    "core_problem",
    "who_involved",
    "trigger",
    "timeframe",
    "goal",
    "prior_attempt",
    "desired_outcome",
}
STYLE_SIGNAL_VALUES = {
    "prefers_brief_response",
    "prefers_gentle_tone",
    "prefers_direct_tone",
    "hesitant_to_open_up",
    "none",
}
USER_STATE_SIGNAL_VALUES = {
    "overwhelmed",
    "emotionally_fragile",
    "stable_enough",
    "ruminating",
    "defensive",
    "none",
}
DEFAULT_CASE_SLOTS = {
    "core_problem": "",
    "who_involved": "",
    "trigger": "",
    "timeframe": "",
    "prior_attempt": "",
    "goal": "",
    "desired_outcome": "",
}
STEP_TRACE_LEVEL_OFF = "off"
STEP_TRACE_LEVEL_META = "meta"
STEP_TRACE_LEVEL_FULL = "full"
STEP_TRACE_FULL_MAX_STR_CHARS = 2000
STEP_TRACE_FULL_MAX_LIST_ITEMS = 20
STEP_TRACE_FULL_MAX_DICT_ITEMS = 40
STEP_TRACE_META_MAX_ITEMS = 12
STEP_TRACE_META_PREVIEW_CHARS = 240


def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event string."""

    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@dataclass
class RuntimeState:
    """In-memory state passed between foundation runtime steps."""

    request_payload: object
    identity: object
    quota_window: object
    clear_guest_cookie: bool = False
    chat: object | None = None
    case: object | None = None
    turn: ChatTurn | None = None
    triage_decision: TriageDecision = TriageDecision.CONTINUE_TO_FULL_REASONING
    triage_result: TriageResult | None = None
    response_method: ResponseMethod = ResponseMethod.ASK
    runtime_bundle: dict = field(default_factory=dict)
    response_text: str = ""
    case_resolution_status: str = "unknown"
    case_resolution_source: str = "unknown"
    reasoning_control: dict[str, Any] | None = None
    reasoning_result: dict[str, Any] = field(default_factory=dict)
    reasoning_gateway_retry_count: int = 0
    reasoning_corrective_retry_count: int = 0
    normalized_reasoning_result: dict[str, Any] = field(default_factory=dict)
    final_safety_state: str = "normal"
    retrieval_required: bool = False
    needs_chat_display_name_suggestion: bool = False
    step_trace_level: str = STEP_TRACE_LEVEL_OFF
    step_traces: list[dict[str, Any]] = field(default_factory=list)


class RuntimeOrchestrator:
    """Coordinate one chat turn through the MVP 12-step foundation path."""

    def __init__(self, gate: RequestGatePipeline | None = None, llm_gateway: LLMGateway | None = None) -> None:
        """Create an orchestrator with injectable collaborators for tests."""

        self.gate = gate or RequestGatePipeline()
        self.chat_context = ChatContextService()
        self.llm_gateway = llm_gateway or LLMGateway()
        self.triage = FastTriageService(self.llm_gateway)
        self.config_service = RuntimeConfigService()
        self.quota_service = QuotaService()
        self.bundle_service = RuntimeBundleService()
        self.embedding_service = EmbeddingService(self.llm_gateway)
        self.reranker_client = RerankerClient()
        self.prompt_assembly_service = PromptAssemblyService()
        self.response_generation_service = ResponseGenerationService(self.llm_gateway)
        self.finalization_service = PostTurnFinalizationService(
            llm_gateway=self.llm_gateway,
            quota_service=self.quota_service,
        )
        self.retrieval_service = KnowledgeRetrievalService(
            llm_gateway=self.llm_gateway,
            embedding_service=self.embedding_service,
            reranker_client=self.reranker_client,
        )

    def stream(self, gate_result: GateResult) -> Iterator[str]:
        """SSE event generator for a post-gate chat turn.

        Gate must have already passed before calling this method.
        Yields SSE event strings at each stage of the turn lifecycle.
        """

        state = RuntimeState(
            request_payload=gate_result.payload,
            identity=gate_result.identity,
            quota_window=gate_result.quota_window,
            clear_guest_cookie=gate_result.clear_guest_cookie,
        )
        self._resolve_step_trace_level(state)

        try:
            self._run_traced_step(
                state=state,
                step_key="step3_resolve_chat_context",
                runner=lambda: self._resolve_chat_context(state),
                input_data={"chat_id": str(state.request_payload.chat_id) if state.request_payload.chat_id else None},
                output_builder=lambda _result: {
                    "chat_id": str(state.chat.id) if state.chat is not None else None,
                    "chat_display_name": state.chat.chat_display_name if state.chat is not None else "",
                },
            )
            self._run_traced_step(
                state=state,
                step_key="step3_create_turn",
                runner=lambda: self._create_turn(state),
                input_data={"message_chars": len(state.request_payload.message or "")},
                output_builder=lambda _result: {"turn_id": str(state.turn.id) if state.turn is not None else None},
            )
            self._run_traced_step(
                state=state,
                step_key="step4_fast_triage",
                runner=lambda: self._fast_triage(state),
                input_data={"turn_id": str(state.turn.id) if state.turn is not None else None},
                output_builder=lambda _result: {
                    "triage_decision": state.triage_decision.value,
                    "triage_source": state.triage_result.source if state.triage_result else "unknown",
                },
            )
            control_response = self._run_traced_step(
                state=state,
                step_key="step4_control_branch",
                runner=lambda: self._handle_control_branch_if_needed(state),
                input_data={"triage_decision": state.triage_decision.value},
                output_builder=lambda result: {
                    "is_control": result is not None,
                    "response_method": result.response_method.value if result is not None else None,
                    "persist_turn": result.persist_turn if result is not None else None,
                },
            )
            if control_response is not None:
                control_quota_exhausted = self._run_traced_step(
                    state=state,
                    step_key="step12_control_quota_state",
                    runner=lambda: self._quota_exhausted_after_turn(state),
                    input_data={"control_response_method": control_response.response_method.value},
                    output_builder=lambda result: {"quota_exhausted_after_turn": bool(result)},
                )
                yield _sse_event("response", {"response_key": control_response.response_key})
                yield _sse_event("done", {
                    "turn_id": str(state.turn.id) if state.turn is not None else None,
                    "chat_id": str(state.chat.id),
                    "chat_display_name": self._chat_display_name_for_done(state),
                    "response_method": control_response.response_method.value,
                    "status": "completed",
                    "quota_exhausted_after_turn": control_quota_exhausted,
                })
                # Control branch exits immediately after persisted/non-persisted triage response.
                return
            self._run_traced_step(
                state=state,
                step_key="step5_resolve_case",
                runner=lambda: self._resolve_case(state),
                input_data={"chat_id": str(state.chat.id) if state.chat is not None else None},
                output_builder=lambda _result: {
                    "case_id": str(state.case.id) if state.case is not None else None,
                    "case_resolution_status": state.case_resolution_status,
                    "case_resolution_source": state.case_resolution_source,
                },
            )
            self._run_traced_step(
                state=state,
                step_key="step6_runtime_bundle",
                runner=lambda: self._load_runtime_bundle(state),
                output_builder=lambda _result: {
                    "bundle_keys": sorted(state.runtime_bundle.keys()),
                    "recent_turn_count": len(state.runtime_bundle.get("recent_turns", [])),
                    "memory_count": len(state.runtime_bundle.get("long_term_memory", [])),
                },
            )
            self._run_traced_step(
                state=state,
                step_key="step7_full_reasoning",
                runner=lambda: self._full_reasoning(state),
                output_builder=lambda _result: {
                    "intent": state.reasoning_result.get("intent"),
                    "action_recommended": state.reasoning_result.get("action_recommended"),
                    "risk_flags": state.reasoning_result.get("risk_flags", []),
                },
            )
            self._run_traced_step(
                state=state,
                step_key="step8_validate_select_method",
                runner=lambda: self._validate_and_select_response_method(state),
                output_builder=lambda _result: {
                    "response_method": state.response_method.value,
                    "final_safety_state": state.final_safety_state,
                    "retrieval_required": state.retrieval_required,
                },
            )
            self._run_traced_step(
                state=state,
                step_key="step9_knowledge_retrieval",
                runner=lambda: self._knowledge_retrieval(state),
                output_builder=lambda _result: state.runtime_bundle.get("retrieval_debug_meta", {}),
            )
            self._run_traced_step(
                state=state,
                step_key="step10_prompt_assembly",
                runner=lambda: self._prompt_assembly(state),
                output_builder=lambda _result: state.runtime_bundle.get("prompt_debug_meta", {}),
            )
            self._response_generation_and_persist(state)
        except LLMGatewayError as exc:
            if state.turn is not None:
                state.turn.status = TurnStatus.FAILED.value
                state.turn.step12_finalization_status = Step12FinalizationStatus.FAILED.value
                state.turn.usage_accounting_status = UsageAccountingStatus.FAILED.value
                runtime_metadata = state.turn.runtime_metadata if isinstance(state.turn.runtime_metadata, dict) else {}
                if state.step_traces:
                    runtime_metadata["step_traces"] = state.step_traces
                state.turn.runtime_metadata = runtime_metadata
                state.turn.runtime_metadata["error"] = exc.code
                state.turn.runtime_metadata["error_status"] = exc.status_code
                state.turn.save(
                    update_fields=[
                        "status",
                        "step12_finalization_status",
                        "usage_accounting_status",
                        "runtime_metadata",
                    ]
                )
            yield _sse_event("error", {"error": exc.code, "status_code": exc.status_code})
            return
        except Exception as exc:
            if state.turn is not None:
                state.turn.status = TurnStatus.FAILED.value
                if state.turn.step12_finalization_status in {
                    Step12FinalizationStatus.PENDING.value,
                    Step12FinalizationStatus.PROCESSING.value,
                }:
                    state.turn.step12_finalization_status = Step12FinalizationStatus.FAILED.value
                runtime_metadata = state.turn.runtime_metadata if isinstance(state.turn.runtime_metadata, dict) else {}
                if state.step_traces:
                    runtime_metadata["step_traces"] = state.step_traces
                state.turn.runtime_metadata = runtime_metadata
                state.turn.runtime_metadata["error"] = exc.__class__.__name__
                state.turn.save(update_fields=["status", "step12_finalization_status", "runtime_metadata"])
            yield _sse_event("error", {"error": "internal_error", "status_code": 500})
            raise

        # Stream response to client immediately after Step 11 — before Step 12 LLM calls.
        # quota_exhausted uses the same lightweight DB check as the control branch path.
        # The gate barrier (step12_finalization_status=PENDING) blocks the next turn until
        # Step 12 completes, so state consistency is preserved without delaying the user.
        quota_exhausted = self._quota_exhausted_after_turn(state)
        yield _sse_event("response", {"text": state.response_text})
        done_method = self._effective_response_method(state)
        yield _sse_event("done", {
            "turn_id": str(state.turn.id),
            "chat_id": str(state.chat.id),
            "chat_display_name": self._chat_display_name_for_done(state),
            "response_method": done_method.value,
            "status": state.turn.status,
            "quota_exhausted_after_turn": quota_exhausted,
        })

        # Step 12 runs after done is sent. Errors here are best-effort — they cannot
        # become SSE events. The finalization service logs and sets PARTIAL/FAILED status.
        # On unexpected exception, release the gate barrier so the next turn isn't
        # permanently blocked by a PENDING/PROCESSING step12_finalization_status.
        try:
            self._post_turn_finalization(state)
        except Exception as exc:
            logger.exception("step12_post_done_unhandled", exc_info=exc)
            if state.turn is not None and state.turn.step12_finalization_status in {
                Step12FinalizationStatus.PENDING.value,
                Step12FinalizationStatus.PROCESSING.value,
            }:
                state.turn.step12_finalization_status = Step12FinalizationStatus.FAILED.value
                state.turn.save(update_fields=["step12_finalization_status"])

    def _resolve_chat_context(self, state: RuntimeState) -> None:
        """Step 3: load or create a frontend chat thread."""

        state.chat = self.chat_context.resolve_chat(
            identity=state.identity,
            chat_id=state.request_payload.chat_id,
            message=state.request_payload.message,
        )

    def _fast_triage(self, state: RuntimeState) -> None:
        """Step 4: fast triage classification before Step 5+ path selection."""

        state.triage_result = self.triage.decide(chat=state.chat, current_turn=state.turn)
        state.triage_decision = state.triage_result.decision
        if state.turn is not None and state.turn.triage_decision != state.triage_decision.value:
            state.turn.triage_decision = state.triage_decision.value
            state.turn.save(update_fields=["triage_decision"])

    def _handle_control_branch_if_needed(self, state: RuntimeState) -> ControlResponse | None:
        """Persist or discard control turns depending on triage decision."""

        control_response = self.triage.control_response_for_decision(state.triage_decision)
        if control_response is None:
            return None

        if control_response.persist_turn:
            self._persist_crisis_control_turn(state=state, control_response=control_response)
            return control_response

        if state.turn is not None:
            state.turn.delete()
            state.turn = None
        return control_response

    def _persist_crisis_control_turn(self, *, state: RuntimeState, control_response: ControlResponse) -> None:
        """Persist crisis control response without running full Step 5+ pipeline."""

        if state.turn is None:
            return
        state.response_method = control_response.response_method
        state.response_text = ""
        state.turn.runtime_metadata = {
            "runtime_path": "step4_control_short_circuit",
            "triage_decision": state.triage_decision.value,
            "triage_source": state.triage_result.source if state.triage_result else "unknown",
            "safety_control": True,
            "response_key": control_response.response_key,
            "exclude_from_memory_updates": True,
            "step_traces": state.step_traces,
        }
        state.turn.save(update_fields=["runtime_metadata"])
        state.turn.mark_completed(state.response_text, state.response_method)
        state.turn.usage_accounting_status = UsageAccountingStatus.FINALIZED.value
        state.turn.step12_finalization_status = Step12FinalizationStatus.FINALIZED.value
        state.turn.quota_exhausted_after_turn = self._quota_exhausted_after_turn(state)
        state.turn.save(
            update_fields=[
                "usage_accounting_status",
                "step12_finalization_status",
                "quota_exhausted_after_turn",
            ]
        )
        state.chat.touch()

    def _resolve_case(self, state: RuntimeState) -> None:
        """Step 5: resolve case context for continue-to-reasoning path."""

        resolution = self.chat_context.resolve_case(
            identity=state.identity,
            chat=state.chat,
            message=state.request_payload.message,
            turn=state.turn,
            llm_gateway=self.llm_gateway,
        )
        state.case = resolution.case
        state.case_resolution_status = resolution.status
        state.case_resolution_source = resolution.source
        if state.turn is not None and state.turn.case_id != (state.case.id if state.case else None):
            state.turn.case = state.case
            state.turn.save(update_fields=["case"])

    def _create_turn(self, state: RuntimeState) -> None:
        """Step 3 intake: persist turn anchor right after chat context resolution."""

        # Mark first-turn chat naming path before inserting the current turn.
        state.needs_chat_display_name_suggestion = not state.chat.turns.exists()
        state.runtime_bundle["needs_chat_display_name_suggestion"] = (
            state.needs_chat_display_name_suggestion
        )

        state.turn = ChatTurn.objects.create(
            **state.identity.owner_kwargs(),
            chat=state.chat,
            case=None,
            user_message_text=state.request_payload.message.strip(),
            status=TurnStatus.PROCESSING.value,
            triage_decision=state.triage_decision.value,
        )

    def _load_runtime_bundle(self, state: RuntimeState) -> None:
        """Step 6: assemble canonical runtime bundle once."""

        state.runtime_bundle = self.bundle_service.build_bundle(
            chat=state.chat,
            turn=state.turn,
            case=state.case,
            identity=state.identity,
            current_message=state.request_payload.message,
        )

    def _full_reasoning(self, state: RuntimeState) -> None:
        """Step 7: call full_reasoning and normalize structured reasoning output."""

        prompt_messages = self._build_reasoning_prompt(state)
        retries = 0
        while True:
            try:
                completion = self.llm_gateway.complete(
                    operation_key=OperationKey.FULL_REASONING,
                    turn=state.turn,
                    prompt_messages=prompt_messages,
                )
                break
            except LLMGatewayError as exc:
                if exc.code not in TRANSIENT_REASONING_ERROR_CODES or retries >= MAX_REASONING_GATEWAY_RETRIES:
                    raise
                retries += 1
        state.reasoning_gateway_retry_count = retries
        state.reasoning_result = self._normalize_reasoning_result(completion.text)
        # Mirror normalized reasoning into runtime_bundle for downstream consumers.
        state.runtime_bundle["reasoning_result"] = state.reasoning_result

    def _build_reasoning_prompt(self, state: RuntimeState) -> list[dict[str, str]]:
        """Build Step 7 prompt from Step 6 bundle and optional corrective controls."""

        payload: dict[str, Any] = {
            "runtime_bundle": {
                "current_message": state.runtime_bundle.get("current_message", ""),
                "recent_turns": state.runtime_bundle.get("recent_turns", []),
                "context_summary": state.runtime_bundle.get("context_summary", ""),
                "user_profile": state.runtime_bundle.get("user_profile", {}),
                "user_preference": state.runtime_bundle.get("user_preference", {}),
                "user_state": state.runtime_bundle.get("user_state", {}),
                "long_term_memory": state.runtime_bundle.get("long_term_memory", []),
            }
        }
        if state.reasoning_control:
            payload["reasoning_control"] = state.reasoning_control
        return [
            {"role": "system", "content": FULL_REASONING_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

    def _normalize_reasoning_result(self, raw_text: str) -> dict[str, Any]:
        """Normalize full_reasoning output into canonical Step 7 schema."""

        parsed = self._parse_reasoning_json(raw_text)
        risk_flags = self._normalize_enum_list(parsed.get("risk_flags"), RISK_FLAG_VALUES, ["none"])
        intent = self._normalize_enum(parsed.get("intent"), INTENT_VALUES, "unclear")
        raw_action = parsed.get("action_recommended")
        action = self._normalize_enum(
            raw_action.upper() if isinstance(raw_action, str) else raw_action,
            {item.value for item in CONVERSATIONAL_RESPONSE_METHODS},
            ResponseMethod.ASK.value,
        )
        required_slots = self._normalize_enum_list(
            parsed.get("required_next_slots"),
            REQUIRED_NEXT_SLOT_VALUES,
            ["core_problem"],
        )
        style_signals = self._normalize_enum_list(parsed.get("style_signals"), STYLE_SIGNAL_VALUES, ["none"])
        user_state_signals = self._normalize_enum_list(parsed.get("user_state_signals"), USER_STATE_SIGNAL_VALUES, ["none"])
        case_slots = self._normalize_case_slots(parsed.get("case_slots"))
        turn_strategy = self._normalize_turn_strategy(parsed.get("turn_strategy"))
        explicit_profile_facts = self._normalize_string_list(parsed.get("explicit_profile_facts"))
        suggested_name = parsed.get("suggested_chat_display_name")
        if not isinstance(suggested_name, str) or not suggested_name.strip():
            suggested_name = None
        else:
            suggested_name = suggested_name.strip()[:120]

        return {
            "risk_flags": risk_flags,
            "intent": intent,
            "action_recommended": action,
            "is_context_sufficient": bool(parsed.get("is_context_sufficient", False)),
            "required_next_slots": required_slots,
            "case_slots": case_slots,
            "turn_strategy": turn_strategy,
            "explicit_profile_facts": explicit_profile_facts,
            "style_signals": style_signals,
            "user_state_signals": user_state_signals,
            "suggested_chat_display_name": suggested_name,
        }

    @staticmethod
    def _parse_reasoning_json(raw_text: str) -> dict[str, Any]:
        """Return parsed object or empty dict when payload is not valid JSON object."""

        try:
            parsed = json.loads(raw_text.strip())
        except (json.JSONDecodeError, AttributeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _normalize_enum(value: object, allowed: set[str], default: str) -> str:
        """Normalize one enum-like value into an allowed canonical value."""

        if isinstance(value, str) and value in allowed:
            return value
        return default

    @staticmethod
    def _normalize_enum_list(value: object, allowed: set[str], default: list[str]) -> list[str]:
        """Normalize one enum-list field, removing unknown/duplicate values."""

        if not isinstance(value, list):
            return default
        normalized: list[str] = []
        for item in value:
            if isinstance(item, str) and item in allowed and item not in normalized:
                normalized.append(item)
        return normalized or default

    @staticmethod
    def _normalize_string_list(value: object) -> list[str]:
        """Normalize generic list[str] fields with lightweight cleanup."""

        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned:
                    normalized.append(cleaned[:240])
        return normalized

    @staticmethod
    def _normalize_case_slots(value: object) -> dict[str, str]:
        """Normalize case slot object to canonical fixed keys."""

        normalized = dict(DEFAULT_CASE_SLOTS)
        if not isinstance(value, dict):
            return normalized
        for key in DEFAULT_CASE_SLOTS:
            candidate = value.get(key)
            if isinstance(candidate, str):
                normalized[key] = candidate.strip()[:400]
        return normalized

    @staticmethod
    def _normalize_turn_strategy(value: object) -> dict[str, object]:
        """Normalize turn strategy object to required minimal shape."""

        focus = ""
        angle = ""
        avoid: list[str] = []
        if isinstance(value, dict):
            focus_value = value.get("focus")
            angle_value = value.get("angle")
            avoid_value = value.get("avoid")
            if isinstance(focus_value, str):
                focus = focus_value.strip()[:240]
            if isinstance(angle_value, str):
                angle = angle_value.strip()[:240]
            if isinstance(avoid_value, list):
                avoid = [item.strip()[:200] for item in avoid_value if isinstance(item, str) and item.strip()]
        return {"focus": focus, "angle": angle, "avoid": avoid}

    def _validate_and_select_response_method(self, state: RuntimeState) -> None:
        """Step 8: validate reasoning, apply safety gates, and select response method."""

        while True:
            normalized = self._normalize_reasoning_from_state(state.reasoning_result)
            schema_heavy_issue = self._schema_heavy_issue(state.reasoning_result)
            normalized["required_next_slots"] = self._remove_fulfilled_required_slots(
                normalized["required_next_slots"],
                normalized["case_slots"],
            )
            hard_override = self._hard_safety_method(normalized["risk_flags"])

            if hard_override is not None:
                state.response_method = hard_override
                state.final_safety_state = self._final_safety_state_for_method(hard_override)
                state.retrieval_required = False
                state.normalized_reasoning_result = normalized
                self._apply_suggested_chat_display_name(state)
                break

            heavy_feedback = schema_heavy_issue
            if heavy_feedback is not None:
                if state.reasoning_corrective_retry_count < MAX_REASONING_CORRECTIVE_RETRIES:
                    state.reasoning_corrective_retry_count += 1
                    state.reasoning_control = {
                        "is_corrective_retry": True,
                        "retry_count": state.reasoning_corrective_retry_count,
                        "validation_error_feedback": heavy_feedback,
                    }
                    self._full_reasoning(state)
                    continue
                state.response_method = ResponseMethod.ASK
                state.final_safety_state = "normal"
                state.retrieval_required = False
                state.normalized_reasoning_result = normalized
                self._apply_suggested_chat_display_name(state)
                break

            state.reasoning_control = None
            method = self._select_conversational_method(normalized)
            if method != ResponseMethod.ASK and normalized["required_next_slots"]:
                normalized["required_next_slots"] = []
            if method == ResponseMethod.ASK and not normalized["required_next_slots"]:
                normalized["required_next_slots"] = ["core_problem"]
            state.response_method = method
            state.final_safety_state = "normal"
            state.retrieval_required = method == ResponseMethod.TEACH
            state.normalized_reasoning_result = normalized
            self._apply_suggested_chat_display_name(state)
            break

        state.runtime_bundle["normalized_reasoning_result"] = state.normalized_reasoning_result
        state.runtime_bundle["final_safety_state"] = state.final_safety_state
        state.runtime_bundle["response_method"] = state.response_method.value
        state.runtime_bundle["retrieval_required"] = state.retrieval_required

    def _normalize_reasoning_from_state(self, value: object) -> dict[str, Any]:
        """Normalize any runtime reasoning payload into canonical schema."""

        if not isinstance(value, dict):
            return self._normalize_reasoning_result("{}")
        return {
            "risk_flags": self._normalize_enum_list(value.get("risk_flags"), RISK_FLAG_VALUES, ["none"]),
            "intent": self._normalize_enum(value.get("intent"), INTENT_VALUES, "unclear"),
            "action_recommended": self._normalize_enum(
                value.get("action_recommended", "").upper() if isinstance(value.get("action_recommended"), str) else value.get("action_recommended"),
                {item.value for item in ResponseMethod},
                ResponseMethod.ASK.value,
            ),
            "is_context_sufficient": bool(value.get("is_context_sufficient", False)),
            "required_next_slots": self._normalize_enum_list(
                value.get("required_next_slots"),
                REQUIRED_NEXT_SLOT_VALUES,
                ["core_problem"],
            ),
            "case_slots": self._normalize_case_slots(value.get("case_slots")),
            "turn_strategy": self._normalize_turn_strategy(value.get("turn_strategy")),
            "explicit_profile_facts": self._normalize_string_list(value.get("explicit_profile_facts")),
            "style_signals": self._normalize_enum_list(value.get("style_signals"), STYLE_SIGNAL_VALUES, ["none"]),
            "user_state_signals": self._normalize_enum_list(
                value.get("user_state_signals"),
                USER_STATE_SIGNAL_VALUES,
                ["none"],
            ),
            "suggested_chat_display_name": value.get("suggested_chat_display_name")
            if isinstance(value.get("suggested_chat_display_name"), str)
            else None,
        }

    @staticmethod
    def _schema_heavy_issue(reasoning_result: object) -> dict[str, Any] | None:
        """Return corrective feedback when Step 7 output has heavy schema violations."""

        if not isinstance(reasoning_result, dict):
            return {
                "error_type": "schema_fail_heavy",
                "error_codes": ["reasoning_result_not_object"],
                "must_fix_fields": ["reasoning_result"],
                "must_preserve": ["risk_flags"],
            }

        errors: list[str] = []
        must_fix_fields: list[str] = []
        required_core_fields = {
            "risk_flags",
            "intent",
            "action_recommended",
            "is_context_sufficient",
            "required_next_slots",
            "case_slots",
            "turn_strategy",
            "explicit_profile_facts",
            "style_signals",
            "user_state_signals",
        }
        missing = sorted(field for field in required_core_fields if field not in reasoning_result)
        if missing:
            errors.append("missing_required_fields")
            must_fix_fields.extend(missing)

        case_slots = reasoning_result.get("case_slots")
        if case_slots is not None and not isinstance(case_slots, dict):
            errors.append("case_slots_not_object")
            must_fix_fields.append("case_slots")

        if errors:
            return {
                "error_type": "schema_fail_heavy",
                "error_codes": sorted(set(errors)),
                "must_fix_fields": sorted(set(must_fix_fields)),
                "must_preserve": ["risk_flags"],
            }
        return None

    @staticmethod
    def _remove_fulfilled_required_slots(required_slots: list[str], case_slots: dict[str, str]) -> list[str]:
        """Remove required slots that are already filled in case slots."""

        return [slot for slot in required_slots if not case_slots.get(slot, "").strip()]

    @staticmethod
    def _hard_safety_method(risk_flags: list[str]) -> ResponseMethod | None:
        """Map hard safety flags to forced response methods."""

        flags = set(risk_flags)
        if "crisis_self_harm" in flags or "crisis_harm_others" in flags:
            return ResponseMethod.CRISIS_SAFE_ONLY
        if "minor_age_block" in flags:
            return ResponseMethod.BLOCKED_MINOR
        if "medical_out_of_scope" in flags or "legal_out_of_scope" in flags:
            return ResponseMethod.REDIRECT
        if "policy_bypass" in flags:
            return ResponseMethod.REFUSAL
        if "spam_or_nonsense" in flags:
            return ResponseMethod.SPAM_REPLY
        return None

    @staticmethod
    def _final_safety_state_for_method(method: ResponseMethod) -> str:
        """Map hard safety method to final safety state."""

        mapping = {
            ResponseMethod.CRISIS_SAFE_ONLY: "crisis_only",
            ResponseMethod.BLOCKED_MINOR: "blocked",
            ResponseMethod.REDIRECT: "redirect",
            ResponseMethod.REFUSAL: "refusal",
            ResponseMethod.SPAM_REPLY: "spam",
        }
        return mapping.get(method, "normal")

    def _select_conversational_method(self, normalized: dict[str, Any]) -> ResponseMethod:
        """Return the conversational method from Step 7 reasoning without override.

        Step 7 (full_reasoning) owns the method decision. Step 8 applies only hard safety
        overrides (via _hard_safety_method) and structural cleanup; it does not second-guess
        the LLM's choice here.
        """
        return ResponseMethod(normalized["action_recommended"])

    def _knowledge_retrieval(self, state: RuntimeState) -> None:
        """Step 9: retrieval pipeline for TEACH path with non-fatal degradation."""

        gate_pass = (
            state.response_method == ResponseMethod.TEACH
            and state.retrieval_required
            and state.final_safety_state == "normal"
        )
        if not gate_pass:
            retrieval_debug_meta = {"retrieval_status": "skipped"}
            state.runtime_bundle["retrieval_result"] = None
            state.runtime_bundle["retrieval_debug_meta"] = retrieval_debug_meta
            return

        outcome = self.retrieval_service.run(state=state)
        state.runtime_bundle["retrieval_result"] = outcome.retrieval_result
        state.runtime_bundle["retrieval_debug_meta"] = outcome.retrieval_debug_meta

    def _apply_suggested_chat_display_name(self, state: RuntimeState) -> None:
        """Apply Step 7 suggested chat title for the first turn of a new chat."""

        if not state.needs_chat_display_name_suggestion:
            return
        if state.chat is None:
            return

        suggested = state.normalized_reasoning_result.get("suggested_chat_display_name")
        if not isinstance(suggested, str):
            return
        clean_name = suggested.strip()
        if not clean_name:
            return
        clean_name = clean_name[:120]
        if clean_name == state.chat.chat_display_name:
            return

        state.chat.chat_display_name = clean_name
        state.chat.save(update_fields=["chat_display_name", "updated_at"])
        state.runtime_bundle["chat_display_name_applied"] = True

    def _chat_display_name_for_done(self, state: RuntimeState) -> str:
        """Return canonical chat display name emitted in SSE done event."""

        if state.chat is None:
            return CHAT_DISPLAY_NAME_FALLBACK
        return self.chat_context.chat_summary_payload(state.chat)["chat_display_name"]

    def _prompt_assembly(self, state: RuntimeState) -> None:
        """Step 10: build minimal prompt messages for response generation."""

        result = self.prompt_assembly_service.build(state=state)
        state.runtime_bundle["prompt_messages"] = result.prompt_messages
        state.runtime_bundle["prompt_debug_meta"] = result.prompt_debug_meta

    def _response_generation_and_persist(self, state: RuntimeState) -> None:
        """Step 11: generate a foundation response and persist the final turn."""

        started = time.perf_counter()
        try:
            result = self.response_generation_service.run(state=state, rebuild_prompt=self._prompt_assembly)
            state.response_text = result.response_text
            final_method = self._effective_response_method(state)
            state.runtime_bundle["effective_response_method"] = final_method.value
            state.runtime_bundle.pop("generation_validation_feedback", None)
            self._append_step_trace(
                state=state,
                step_key="step11_response_generation_persist",
                status="ok",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                input_data={
                    "step8_response_method": state.response_method.value,
                    "effective_response_method": final_method.value,
                    "retrieval_required": state.retrieval_required,
                },
                output_data={
                    "generation_retry_count": result.metadata.get("generation_retry_count", 0),
                    "validation_outcome": result.metadata.get("validation_outcome", {}),
                    "fallback_used": result.metadata.get("fallback_used", False),
                    "response_chars": len(state.response_text or ""),
                },
            )
            state.turn.runtime_metadata = {
                "runtime_path": "step11_response_generation_validation_persist",
                "triage_decision": state.triage_decision.value,
                "triage_source": state.triage_result.source if state.triage_result else "unknown",
                "retrieval_required": state.retrieval_required,
                "case_resolution_status": state.case_resolution_status,
                "case_resolution_source": state.case_resolution_source,
                "prompt_debug_meta": state.runtime_bundle.get("prompt_debug_meta", {}),
                "generation_retry_count": result.metadata.get("generation_retry_count", 0),
                "validation_outcome": result.metadata.get("validation_outcome", {}),
                "fallback_used": result.metadata.get("fallback_used", False),
                "reasoning_gateway_retry_count": state.reasoning_gateway_retry_count,
                "reasoning_corrective_retry_count": state.reasoning_corrective_retry_count,
                "reasoning_corrective_applied": state.reasoning_corrective_retry_count > 0,
                "effective_response_method": final_method.value,
                "step8_response_method": state.response_method.value,
                "step_traces": state.step_traces,
            }
            state.turn.save(update_fields=["runtime_metadata"])
            state.turn.mark_completed(state.response_text, final_method)
            state.chat.touch()
            if state.case is not None:
                state.case.touch()
        except Exception as exc:
            self._append_step_trace(
                state=state,
                step_key="step11_response_generation_persist",
                status="error",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                input_data={
                    "step8_response_method": state.response_method.value,
                    "retrieval_required": state.retrieval_required,
                },
                output_data={"error": exc.__class__.__name__},
            )
            raise

    @staticmethod
    def _effective_response_method(state: RuntimeState) -> ResponseMethod:
        """Resolve final response method used by Step 10/11 execution."""

        method_value = state.runtime_bundle.get("effective_response_method")
        if isinstance(method_value, str):
            try:
                return ResponseMethod(method_value)
            except ValueError:
                pass
        return state.response_method

    def _post_turn_finalization(self, state: RuntimeState) -> None:
        """Step 12: synchronously finalize usage and quota."""
        started = time.perf_counter()
        try:
            outcome = self.finalization_service.run(state=state)
            self._append_step_trace(
                state=state,
                step_key="step12_post_turn_finalization",
                status="ok",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                output_data={
                    "step12_finalization_status": outcome.step12_finalization_status,
                    "usage_accounting_status": outcome.usage_accounting_status,
                    "consolidation_meta": outcome.consolidation_meta,
                },
            )
            runtime_metadata = state.turn.runtime_metadata if isinstance(state.turn.runtime_metadata, dict) else {}
            runtime_metadata["step_traces"] = state.step_traces
            state.turn.runtime_metadata = runtime_metadata
            state.turn.save(update_fields=["runtime_metadata"])
        except Exception as exc:
            self._append_step_trace(
                state=state,
                step_key="step12_post_turn_finalization",
                status="error",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                output_data={"error": exc.__class__.__name__},
            )
            raise

    def _resolve_step_trace_level(self, state: RuntimeState) -> None:
        """Resolve runtime step trace level from admin config with fail-safe fallback."""

        try:
            level = self.config_service.step_trace_level()
        except Exception:
            logger.exception("step_trace_level_resolve_failed")
            level = STEP_TRACE_LEVEL_OFF
        if level not in {STEP_TRACE_LEVEL_OFF, STEP_TRACE_LEVEL_META, STEP_TRACE_LEVEL_FULL}:
            level = STEP_TRACE_LEVEL_OFF
        state.step_trace_level = level

    def _run_traced_step(
        self,
        *,
        state: RuntimeState,
        step_key: str,
        runner,
        input_data: object | None = None,
        output_builder=None,
    ):
        """Run one step and append observability trace according to configured level."""

        started = time.perf_counter()
        result = None
        success = False
        try:
            result = runner()
            success = True
            return result
        except Exception as exc:
            self._append_step_trace(
                state=state,
                step_key=step_key,
                status="error",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                input_data=input_data,
                output_data={"error": exc.__class__.__name__},
            )
            raise
        finally:
            if success:
                output_data = None
                if output_builder is not None:
                    try:
                        output_data = output_builder(result)
                    except Exception as exc:  # pragma: no cover - defensive observability path.
                        output_data = {"trace_output_builder_error": exc.__class__.__name__}
                self._append_step_trace(
                    state=state,
                    step_key=step_key,
                    status="ok",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    input_data=input_data,
                    output_data=output_data,
                )

    def _append_step_trace(
        self,
        *,
        state: RuntimeState,
        step_key: str,
        status: str,
        latency_ms: float,
        input_data: object | None = None,
        output_data: object | None = None,
    ) -> None:
        """Append one step trace entry into state for optional admin observability."""

        if state.step_trace_level == STEP_TRACE_LEVEL_OFF:
            return

        entry: dict[str, Any] = {
            "step": step_key,
            "status": status,
            "latency_ms": int(max(latency_ms, 0)),
        }
        if input_data is not None:
            entry["input"] = self._serialize_step_trace_payload(
                payload=input_data,
                level=state.step_trace_level,
            )
        if output_data is not None:
            entry["output"] = self._serialize_step_trace_payload(
                payload=output_data,
                level=state.step_trace_level,
            )
        state.step_traces.append(entry)

    def _serialize_step_trace_payload(self, *, payload: object, level: str) -> object:
        """Serialize trace payload into a JSON-safe observability representation."""

        if level == STEP_TRACE_LEVEL_FULL:
            return self._sanitize_trace_full(payload)
        return self._summarize_trace_meta(payload)

    def _sanitize_trace_full(self, payload: object) -> object:
        """Return bounded deep payload for full trace mode."""

        if isinstance(payload, str):
            if len(payload) <= STEP_TRACE_FULL_MAX_STR_CHARS:
                return payload
            return f"{payload[:STEP_TRACE_FULL_MAX_STR_CHARS]}...[truncated]"
        if isinstance(payload, dict):
            normalized: dict[str, object] = {}
            items = list(payload.items())[:STEP_TRACE_FULL_MAX_DICT_ITEMS]
            for key, value in items:
                normalized[str(key)] = self._sanitize_trace_full(value)
            if len(payload) > STEP_TRACE_FULL_MAX_DICT_ITEMS:
                normalized["_truncated_keys"] = len(payload) - STEP_TRACE_FULL_MAX_DICT_ITEMS
            return normalized
        if isinstance(payload, list):
            values = [self._sanitize_trace_full(item) for item in payload[:STEP_TRACE_FULL_MAX_LIST_ITEMS]]
            if len(payload) > STEP_TRACE_FULL_MAX_LIST_ITEMS:
                values.append({"_truncated_items": len(payload) - STEP_TRACE_FULL_MAX_LIST_ITEMS})
            return values
        if isinstance(payload, (int, float, bool)) or payload is None:
            return payload
        return str(payload)

    def _summarize_trace_meta(self, payload: object) -> object:
        """Return compact payload summary for meta trace mode."""

        if isinstance(payload, str):
            return {
                "type": "text",
                "chars": len(payload),
                "preview": payload[:STEP_TRACE_META_PREVIEW_CHARS],
            }
        if isinstance(payload, dict):
            summary: dict[str, object] = {}
            keys = sorted(payload.keys())
            for key in keys[:STEP_TRACE_META_MAX_ITEMS]:
                value = payload.get(key)
                summary[str(key)] = self._summarize_trace_meta_scalar(value)
            if len(keys) > STEP_TRACE_META_MAX_ITEMS:
                summary["_truncated_keys"] = len(keys) - STEP_TRACE_META_MAX_ITEMS
            return summary
        if isinstance(payload, list):
            return {
                "type": "list",
                "count": len(payload),
                "sample": [self._summarize_trace_meta_scalar(item) for item in payload[:3]],
            }
        return self._summarize_trace_meta_scalar(payload)

    def _summarize_trace_meta_scalar(self, value: object) -> object:
        """Return compact scalar/shape summary for one meta value."""

        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, str):
            return {
                "type": "text",
                "chars": len(value),
                "preview": value[:STEP_TRACE_META_PREVIEW_CHARS],
            }
        if isinstance(value, dict):
            return {"type": "object", "keys": sorted(value.keys())[:STEP_TRACE_META_MAX_ITEMS], "count": len(value)}
        if isinstance(value, list):
            return {"type": "list", "count": len(value)}
        return str(value)

    def _quota_exhausted_after_turn(self, state: RuntimeState) -> bool:
        """Return latest quota exhaustion state without breaking control-path flow."""

        try:
            window = self.quota_service.current_for_identity(**state.identity.owner_kwargs())
            return bool(window.is_exhausted)
        except Exception:
            logger.exception("quota_exhausted_check_failed")
            return False
