"""Step 12 post-turn finalization service."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from llm_ops.gateway import LLMGateway
from memory.models import MemoryItem
from runtime.operational_logs import record_operational_log
from runtime.prompts import CONTEXT_SUMMARY_UPDATER_SYSTEM, LONG_TERM_MEMORY_EXTRACTOR_SYSTEM
from runtime.services import IdentityStateStoreService, QuotaService
from runtime.usage import aggregate_usage_events
from wismo.contracts.enums import OperationKey, Step12FinalizationStatus, UsageAccountingStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step12Outcome:
    """Finalized Step 12 status and metadata."""

    step12_finalization_status: str
    usage_accounting_status: str
    consolidation_meta: dict[str, Any]


class PostTurnFinalizationService:
    """Finalize usage/quota and consolidate runtime memory/state synchronously."""

    def __init__(
        self,
        *,
        llm_gateway: LLMGateway,
        quota_service: QuotaService,
        state_store: IdentityStateStoreService | None = None,
    ) -> None:
        """Create a service with injectable collaborators."""

        self.llm_gateway = llm_gateway
        self.quota_service = quota_service
        self.state_store = state_store or IdentityStateStoreService()

    def run(self, *, state) -> Step12Outcome:
        """Run Step 12 lifecycle and persist canonical turn statuses."""

        turn = state.turn
        turn.step12_finalization_status = Step12FinalizationStatus.PROCESSING.value
        turn.save(update_fields=["step12_finalization_status"])

        consolidation_meta: dict[str, Any] = {
            "updated_context_summary_id": None,
            "memory_items_upserted_count": 0,
            "profile_fields_updated": [],
            "preference_fields_updated": [],
            "updated_user_state": {},
            "consolidation_log_meta": {"errors": []},
            "turn_token_usage": {},
        }

        consolidation_errors = 0

        try:
            context_result = self._update_context_summary(state=state)
            consolidation_meta["updated_context_summary_id"] = context_result.get("updated_context_summary_id")
            if context_result.get("error"):
                consolidation_errors += 1
                consolidation_meta["consolidation_log_meta"]["errors"].append(context_result["error"])
        except Exception as exc:  # pragma: no cover - defensive path
            consolidation_errors += 1
            logger.exception("step12_context_summary_unhandled", exc_info=exc)
            consolidation_meta["consolidation_log_meta"]["errors"].append("context_summary_unhandled_error")

        try:
            memory_result = self._update_long_term_memory(state=state)
            consolidation_meta["memory_items_upserted_count"] = memory_result.get("memory_items_upserted_count", 0)
            if memory_result.get("error"):
                consolidation_errors += 1
                consolidation_meta["consolidation_log_meta"]["errors"].append(memory_result["error"])
        except Exception as exc:  # pragma: no cover - defensive path
            consolidation_errors += 1
            logger.exception("step12_memory_unhandled", exc_info=exc)
            consolidation_meta["consolidation_log_meta"]["errors"].append("long_term_memory_unhandled_error")

        try:
            reasoning = state.normalized_reasoning_result if isinstance(state.normalized_reasoning_result, dict) else {}
            if state.runtime_bundle.get("identity_state_persisted_in_step8"):
                update_meta = state.runtime_bundle.get("identity_state_update_meta")
                if isinstance(update_meta, dict):
                    consolidation_meta["profile_fields_updated"] = update_meta.get("profile_fields_updated", [])
                    consolidation_meta["preference_fields_updated"] = update_meta.get("preference_fields_updated", [])
                    consolidation_meta["updated_user_state"] = update_meta.get("updated_user_state", {})
            else:
                profile_fields = self.state_store.upsert_user_profile(
                    identity=state.identity,
                    explicit_profile_facts=self._as_string_list(
                        reasoning.get("explicit_profile_facts_next") or reasoning.get("explicit_profile_facts")
                    ),
                )
                preference_fields = self.state_store.upsert_user_preference(
                    identity=state.identity,
                    style_signals=self._as_string_list(
                        reasoning.get("style_signals_next") or reasoning.get("style_signals")
                    ),
                )
                user_state = self.state_store.upsert_user_state(
                    identity=state.identity,
                    user_state_signals=self._as_string_list(
                        reasoning.get("user_state_signals_next") or reasoning.get("user_state_signals")
                    ),
                )
                consolidation_meta["profile_fields_updated"] = profile_fields
                consolidation_meta["preference_fields_updated"] = preference_fields
                consolidation_meta["updated_user_state"] = user_state
        except Exception as exc:  # pragma: no cover - defensive path
            consolidation_errors += 1
            logger.exception("step12_identity_state_update_failed", exc_info=exc)
            consolidation_meta["consolidation_log_meta"]["errors"].append("identity_state_update_failed")

        usage_status = UsageAccountingStatus.FINALIZED.value
        try:
            with transaction.atomic():
                usage_totals = aggregate_usage_events(turn.llm_usage_events.select_for_update())
                quota_window = self.quota_service.current_for_identity(**state.identity.owner_kwargs())
                state.quota_window = quota_window
                quota_snapshot = quota_window.snapshot()
                turn.input_tokens = usage_totals.input_tokens
                turn.cached_input_tokens = usage_totals.cached_input_tokens
                turn.output_tokens = usage_totals.output_tokens
                turn.cache_write_tokens = usage_totals.cache_write_tokens
                turn.total_billable_tokens = usage_totals.total_billable_tokens
                turn.total_observed_tokens = usage_totals.total_observed_tokens
                turn.quota_window_before = quota_snapshot
                turn.quota_window_after = quota_snapshot
                turn.quota_exhausted_after_turn = quota_window.is_exhausted
                consolidation_meta["turn_token_usage"] = {
                    "input_tokens": usage_totals.input_tokens,
                    "cached_input_tokens": usage_totals.cached_input_tokens,
                    "output_tokens": usage_totals.output_tokens,
                    "cache_write_tokens": usage_totals.cache_write_tokens,
                    "total_billable_tokens": usage_totals.total_billable_tokens,
                    "total_observed_tokens": usage_totals.total_observed_tokens,
                }
        except Exception as exc:
            usage_status = UsageAccountingStatus.FAILED.value
            logger.exception("step12_usage_finalization_failed", exc_info=exc)
            consolidation_meta["consolidation_log_meta"]["errors"].append("usage_finalization_failed")

        if usage_status == UsageAccountingStatus.FAILED.value:
            step12_status = Step12FinalizationStatus.FAILED.value
        elif consolidation_errors > 0:
            step12_status = Step12FinalizationStatus.PARTIAL.value
        else:
            step12_status = Step12FinalizationStatus.FINALIZED.value

        if step12_status == Step12FinalizationStatus.FAILED.value:
            record_operational_log(
                event_key="step12_failed",
                component="runtime.finalization",
                message="Step 12 finalization failed",
                context={
                    "errors": consolidation_meta["consolidation_log_meta"]["errors"],
                    "usage_status": usage_status,
                    "turn_id": str(turn.id),
                },
                turn=turn,
            )
        elif step12_status == Step12FinalizationStatus.PARTIAL.value:
            record_operational_log(
                event_key="step12_partial",
                level="warning",
                component="runtime.finalization",
                message="Step 12 finalization partial",
                context={
                    "errors": consolidation_meta["consolidation_log_meta"]["errors"],
                    "consolidation_error_count": consolidation_errors,
                    "turn_id": str(turn.id),
                },
                turn=turn,
            )
        turn.usage_accounting_status = usage_status
        turn.step12_finalization_status = step12_status
        turn.finalized_at = turn.finalized_at or timezone.now()
        runtime_metadata = turn.runtime_metadata if isinstance(turn.runtime_metadata, dict) else {}
        runtime_metadata["step12"] = consolidation_meta
        turn.runtime_metadata = runtime_metadata
        turn.save(
            update_fields=[
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "cache_write_tokens",
                "total_billable_tokens",
                "total_observed_tokens",
                "quota_window_before",
                "quota_window_after",
                "quota_exhausted_after_turn",
                "usage_accounting_status",
                "step12_finalization_status",
                "runtime_metadata",
                "finalized_at",
            ]
        )
        return Step12Outcome(
            step12_finalization_status=step12_status,
            usage_accounting_status=usage_status,
            consolidation_meta=consolidation_meta,
        )

    def _update_context_summary(self, *, state) -> dict[str, Any]:
        if state.case is None:
            return {"updated_context_summary_id": None}
        reasoning = state.normalized_reasoning_result if isinstance(state.normalized_reasoning_result, dict) else {}
        payload = {
            "old_context_summary": state.runtime_bundle.get("context_summary", ""),
            "user_message": state.turn.user_message_text,
            "assistant_response": state.response_text,
            "intent": reasoning.get("intent", ""),
            "case_slots": reasoning.get("case_slots", {}),
        }
        completion = self.llm_gateway.complete(
            operation_key=OperationKey.CONTEXT_SUMMARY_UPDATER,
            turn=state.turn,
            prompt_messages=[
                {
                    "role": "system",
                    "content": CONTEXT_SUMMARY_UPDATER_SYSTEM,
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        parsed: dict[str, Any] = {}
        try:
            loaded = json.loads(completion.text)
            if isinstance(loaded, dict):
                parsed = loaded
        except (json.JSONDecodeError, TypeError):
            return {"updated_context_summary_id": None, "error": "context_summary_parse_failed"}
        has_update = bool(parsed.get("has_meaningful_update"))
        new_summary = parsed.get("new_context_summary_text")
        if not has_update:
            return {"updated_context_summary_id": None}
        if not isinstance(new_summary, str) or not new_summary.strip():
            return {"updated_context_summary_id": None, "error": "context_summary_invalid_output"}
        state.case.context_summary = new_summary.strip()[:4000]
        state.case.save(update_fields=["context_summary", "updated_at"])
        state.runtime_bundle["context_summary"] = state.case.context_summary
        return {"updated_context_summary_id": str(state.case.id)}

    def _update_long_term_memory(self, *, state) -> dict[str, Any]:
        if state.case is None:
            return {"memory_items_upserted_count": 0}
        reasoning = state.normalized_reasoning_result if isinstance(state.normalized_reasoning_result, dict) else {}
        active_record = (
            MemoryItem.objects.filter(case=state.case, segment_status="active", **state.identity.owner_kwargs())
            .order_by("-updated_at", "-created_at", "-id")
            .first()
        )
        recent_closed_records = list(
            MemoryItem.objects.filter(case=state.case, segment_status="closed", **state.identity.owner_kwargs())
            .order_by("-updated_at", "-created_at", "-id")[:2]
        )
        payload = {
            "current_turn": {
                "user_message": state.turn.user_message_text,
                "assistant_response": state.response_text,
            },
            "case_slots": reasoning.get("case_slots", {}),
            "explicit_profile_facts": reasoning.get("explicit_profile_facts_next")
            or reasoning.get("explicit_profile_facts", []),
            "active_segment": self._serialize_segment_for_extractor(active_record),
            "recent_closed_segments": [
                self._serialize_segment_for_extractor(segment) for segment in reversed(recent_closed_records)
            ],
        }
        completion = self.llm_gateway.complete(
            operation_key=OperationKey.LONG_TERM_MEMORY_EXTRACTOR,
            turn=state.turn,
            prompt_messages=[
                {
                    "role": "system",
                    "content": LONG_TERM_MEMORY_EXTRACTOR_SYSTEM,
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        try:
            loaded = json.loads(completion.text)
        except (json.JSONDecodeError, TypeError):
            return {"memory_items_upserted_count": 0, "error": "long_term_memory_parse_failed"}
        if not isinstance(loaded, dict):
            return {"memory_items_upserted_count": 0, "error": "long_term_memory_invalid_output"}

        action = loaded.get("action")
        if not isinstance(action, str):
            return {"memory_items_upserted_count": 0, "error": "long_term_memory_invalid_output"}
        action = action.strip()
        allowed_actions = {
            "no_update",
            "append_active_segment",
            "revise_active_segment",
            "close_active_and_create_new_segment",
        }
        if action not in allowed_actions:
            return {"memory_items_upserted_count": 0, "error": "long_term_memory_invalid_output"}
        if action == "no_update":
            return {"memory_items_upserted_count": 0}

        now = timezone.now()
        upserted_count = 0

        active_update = self._parse_segment_update(loaded.get("active_segment_update"))
        closed_update = self._parse_segment_update(loaded.get("closed_active_segment_update"))
        new_update = self._parse_segment_update(loaded.get("new_segment_update"))

        if action in {"append_active_segment", "revise_active_segment"}:
            if active_update is None:
                return {"memory_items_upserted_count": 0, "error": "long_term_memory_invalid_output"}
            if active_record is None:
                MemoryItem.objects.create(
                    **state.identity.owner_kwargs(),
                    case=state.case,
                    start_turn=state.turn,
                    end_turn=state.turn,
                    segment_status="active",
                    **active_update,
                )
            else:
                active_record.end_turn = state.turn
                self._apply_segment_update(active_record, active_update)
                active_record.save(
                    update_fields=[
                        "user_concern_summary",
                        "assistant_approach_summary",
                        "user_response_summary",
                        "state_shift",
                        "open_loops",
                        "confidence",
                        "end_turn",
                        "updated_at",
                    ]
                )
            return {"memory_items_upserted_count": 1}

        if action == "close_active_and_create_new_segment":
            if new_update is None:
                return {"memory_items_upserted_count": 0, "error": "long_term_memory_invalid_output"}
            if active_record is not None:
                if closed_update is not None:
                    self._apply_segment_update(active_record, closed_update)
                active_record.segment_status = "closed"
                active_record.end_turn = state.turn
                active_record.save(
                    update_fields=[
                        "user_concern_summary",
                        "assistant_approach_summary",
                        "user_response_summary",
                        "state_shift",
                        "open_loops",
                        "confidence",
                        "segment_status",
                        "end_turn",
                        "updated_at",
                    ]
                )
                upserted_count += 1
                MemoryItem.objects.filter(
                    case=state.case,
                    segment_status="active",
                    **state.identity.owner_kwargs(),
                ).exclude(id=active_record.id).update(segment_status="closed", end_turn=state.turn, updated_at=now)
            else:
                # Guardrail: if multiple active rows exist unexpectedly, close them before creating a fresh segment.
                MemoryItem.objects.filter(
                    case=state.case,
                    segment_status="active",
                    **state.identity.owner_kwargs(),
                ).update(segment_status="closed", end_turn=state.turn, updated_at=now)
            MemoryItem.objects.create(
                **state.identity.owner_kwargs(),
                case=state.case,
                start_turn=state.turn,
                end_turn=state.turn,
                segment_status="active",
                **new_update,
            )
            upserted_count += 1
            return {"memory_items_upserted_count": upserted_count}

        return {"memory_items_upserted_count": 0}

    @staticmethod
    def _serialize_segment_for_extractor(segment: MemoryItem | None) -> dict[str, Any] | None:
        if segment is None:
            return None
        open_loops = segment.open_loops if isinstance(segment.open_loops, list) else []
        return {
            "user_concern_summary": segment.user_concern_summary or "",
            "assistant_approach_summary": segment.assistant_approach_summary or "",
            "user_response_summary": segment.user_response_summary or "",
            "state_shift": segment.state_shift or "",
            "open_loops": [item.strip() for item in open_loops if isinstance(item, str) and item.strip()],
            "updated_at": segment.updated_at.isoformat() if segment.updated_at else "",
        }

    @staticmethod
    def _parse_segment_update(value: object) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        user_concern_summary = value.get("user_concern_summary")
        assistant_approach_summary = value.get("assistant_approach_summary")
        user_response_summary = value.get("user_response_summary")
        state_shift = value.get("state_shift")
        open_loops = value.get("open_loops")
        confidence = value.get("confidence")
        if not all(isinstance(item, str) for item in [user_concern_summary, assistant_approach_summary, user_response_summary, state_shift]):
            return None
        loops = [item.strip() for item in open_loops if isinstance(item, str) and item.strip()] if isinstance(open_loops, list) else []
        confidence_value = float(confidence) if isinstance(confidence, (int, float)) else 0.0
        confidence_value = max(0.0, min(1.0, confidence_value))
        return {
            "user_concern_summary": user_concern_summary.strip(),
            "assistant_approach_summary": assistant_approach_summary.strip(),
            "user_response_summary": user_response_summary.strip(),
            "state_shift": state_shift.strip(),
            "open_loops": loops,
            "confidence": confidence_value,
        }

    @staticmethod
    def _apply_segment_update(record: MemoryItem, update: dict[str, Any]) -> None:
        record.user_concern_summary = str(update.get("user_concern_summary") or "")
        record.assistant_approach_summary = str(update.get("assistant_approach_summary") or "")
        record.user_response_summary = str(update.get("user_response_summary") or "")
        record.state_shift = str(update.get("state_shift") or "")
        loops = update.get("open_loops")
        record.open_loops = [item for item in loops if isinstance(item, str)] if isinstance(loops, list) else []
        confidence = update.get("confidence")
        record.confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.0

    @staticmethod
    def _as_string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
        return result
