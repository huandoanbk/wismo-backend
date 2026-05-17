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
            profile_fields = self.state_store.upsert_user_profile(
                identity=state.identity,
                explicit_profile_facts=self._as_string_list(reasoning.get("explicit_profile_facts")),
            )
            preference_fields = self.state_store.upsert_user_preference(
                identity=state.identity,
                style_signals=self._as_string_list(reasoning.get("style_signals")),
            )
            user_state = self.state_store.upsert_user_state(
                identity=state.identity,
                user_state_signals=self._as_string_list(reasoning.get("user_state_signals")),
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
                    "content": (
                        "Return JSON only: has_meaningful_update(boolean), new_context_summary_text(string)."
                    ),
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
        existing_memory_compact = [
            {"memory_type": item.get("memory_type"), "text": item.get("text")}
            for item in state.runtime_bundle.get("long_term_memory", [])
            if isinstance(item, dict)
        ][:20]
        payload = {
            "user_message": state.turn.user_message_text,
            "case_slots": reasoning.get("case_slots", {}),
            "explicit_profile_facts": reasoning.get("explicit_profile_facts", []),
            "existing_memory_compact": existing_memory_compact,
        }
        completion = self.llm_gateway.complete(
            operation_key=OperationKey.LONG_TERM_MEMORY_EXTRACTOR,
            turn=state.turn,
            prompt_messages=[
                {
                    "role": "system",
                    "content": (
                        "Return JSON only: candidate_memory_items[] of objects {memory_type, normalized_text, confidence}."
                    ),
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
        candidates = loaded.get("candidate_memory_items")
        if not isinstance(candidates, list):
            return {"memory_items_upserted_count": 0}

        upserted_count = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            memory_type = candidate.get("memory_type")
            normalized_text = candidate.get("normalized_text")
            confidence = candidate.get("confidence")
            if not isinstance(memory_type, str) or not isinstance(normalized_text, str):
                continue
            if memory_type not in {choice[0] for choice in MemoryItem.MEMORY_TYPE_CHOICES}:
                continue
            text = normalized_text.strip()
            if not text:
                continue
            conf = float(confidence) if isinstance(confidence, (int, float)) else 0.0
            if conf < 0.5:
                continue
            existing = MemoryItem.objects.filter(
                case=state.case,
                is_active=True,
                normalized_text=text,
                **state.identity.owner_kwargs(),
            ).first()
            if existing is not None:
                existing.evidence_count += 1
                existing.confidence = max(existing.confidence, conf)
                existing.evidence_turn = state.turn
                existing.save(update_fields=["evidence_count", "confidence", "evidence_turn", "updated_at"])
                upserted_count += 1
                continue
            MemoryItem.objects.create(
                **state.identity.owner_kwargs(),
                case=state.case,
                evidence_turn=state.turn,
                memory_type=memory_type,
                normalized_text=text,
                confidence=conf,
                evidence_count=1,
                is_active=True,
            )
            upserted_count += 1
        return {"memory_items_upserted_count": upserted_count}

    @staticmethod
    def _as_string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
        return result
