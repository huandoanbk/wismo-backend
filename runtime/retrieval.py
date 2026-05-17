"""Step 9 knowledge retrieval service for TEACH path."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from math import sqrt
from typing import Any

from django.db.models import QuerySet

from knowledge.models import ContentChunk
from llm_ops.errors import LLMGatewayError
from llm_ops.gateway import LLMGateway
from runtime.embedding import EmbeddingService, EmbeddingServiceError
from runtime.prompts import RETRIEVAL_QUERY_BUILDER_SYSTEM
from runtime.reranker import RerankerClient, RerankerError
from wismo.contracts.enums import OperationKey

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalOutcome:
    """Canonical Step 9 output bundle."""

    retrieval_result: dict[str, Any] | None
    retrieval_debug_meta: dict[str, Any]


class KnowledgeRetrievalService:
    """Execute Step 9 TEACH retrieval with non-fatal fallback behavior."""

    def __init__(
        self,
        *,
        llm_gateway: LLMGateway,
        embedding_service: EmbeddingService,
        reranker_client: RerankerClient,
    ) -> None:
        self.llm_gateway = llm_gateway
        self.embedding_service = embedding_service
        self.reranker_client = reranker_client

    def run(self, *, state) -> RetrievalOutcome:
        """Run retrieval pipeline and always return non-fatal outcome."""

        debug = {
            "retrieval_query": "",
            "query_embedding_model": "",
            "dense_top_k": 0,
            "reranker_model": "bge-reranker-v2-m3",
            "reranker_used": False,
            "reranker_failed": False,
            "fallback_to_prerank": False,
            "stitch_llm_used": False,
            "stitch_llm_calls": 0,
            "stitch_applied": False,
            "retrieval_status": "started",
            "query_builder_failed": False,
        }

        retrieval_query, query_meta = self._build_retrieval_query(state=state)
        debug.update(query_meta)
        debug["retrieval_query"] = retrieval_query

        try:
            query_vector, embedding_meta = self.embedding_service.embed_query(query=retrieval_query, turn=state.turn)
            debug.update(embedding_meta)
            debug["query_embedding_model"] = embedding_meta.get("query_embedding_model", "")
        except EmbeddingServiceError:
            logger.exception("Step 9 embedding failed; fallback to no retrieval result.")
            debug["retrieval_status"] = "embedding_failed"
            return RetrievalOutcome(retrieval_result=None, retrieval_debug_meta=debug)

        candidates = self._load_candidates(query_vector=query_vector)
        if not candidates:
            logger.warning("Step 9 retrieval found no enabled candidates.")
            debug["retrieval_status"] = "empty_or_failed"
            return RetrievalOutcome(retrieval_result=None, retrieval_debug_meta=debug)

        debug["dense_top_k"] = len(candidates)

        reranked = candidates
        rerank_score_by_id: dict[str, float] = {}
        try:
            ranked_ids = self.reranker_client.rerank(
                query=retrieval_query,
                candidates=[{"chunk_id": str(item["chunk"].id), "text": item["chunk"].content_text} for item in candidates],
            )
            rank_map = {chunk_id: index for index, chunk_id in enumerate(ranked_ids)}
            reranked = sorted(candidates, key=lambda item: rank_map.get(str(item["chunk"].id), 10_000))
            debug["reranker_used"] = True
            rerank_score_by_id = {
                chunk_id: float(len(ranked_ids) - index)
                for index, chunk_id in enumerate(ranked_ids)
            }
        except (RerankerError, ValueError):
            logger.warning("Step 9 reranker failed; fallback to prerank ordering.", exc_info=True)
            debug["reranker_failed"] = True
            debug["fallback_to_prerank"] = True

        primary = reranked[0]
        stitched = [primary["chunk"]]
        stitch_decision = "KEEP"

        try:
            stitched, stitch_decision, stitch_calls = self._apply_stitch_with_validator(
                state=state,
                primary_chunk=primary["chunk"],
            )
            debug["stitch_llm_used"] = stitch_calls > 0
            debug["stitch_llm_calls"] = stitch_calls
            debug["stitch_applied"] = len(stitched) > 1
        except (LLMGatewayError, ValueError):
            logger.warning("Step 9 stitch validator failed; fallback to primary chunk only.", exc_info=True)
            stitched = [primary["chunk"]]
            debug["stitch_applied"] = False

        unit_text = "\n\n".join(chunk.content_text for chunk in stitched if chunk.content_text)
        if not unit_text.strip():
            logger.warning("Step 9 retrieval produced empty retrieval unit text.")
            debug["retrieval_status"] = "empty_or_failed"
            return RetrievalOutcome(retrieval_result=None, retrieval_debug_meta=debug)

        source = primary["chunk"].source_document
        debug["retrieval_status"] = "ok"
        retrieval_result = {
            "primary_chunk_id": str(primary["chunk"].id),
            "stitched_chunk_ids": [str(chunk.id) for chunk in stitched],
            "retrieval_unit_text": unit_text,
            "source_document_id": str(source.id),
            "source_title": source.title,
            "speaker_or_author": source.speaker_or_author,
            "source_type": source.source_type,
            "topic": primary["chunk"].topic,
            "content_type": primary["chunk"].content_type,
            "dharma_concepts": list(primary["chunk"].dharma_concepts or []),
            "retrieval_score": primary["score"],
            "rerank_score": rerank_score_by_id.get(str(primary["chunk"].id)),
            "rank_final": 1,
            "stitch_span": {
                "count": len(stitched),
                "decision": stitch_decision,
            },
            "retrieval_debug_meta": debug,
            "retrieval_prompt_payload": {
                "primary_chunk_id": str(primary["chunk"].id),
                "stitched_chunk_ids": [str(chunk.id) for chunk in stitched],
                "source_title": source.title,
                "speaker_or_author": source.speaker_or_author,
                "content_text_for_prompt": unit_text,
                "retrieval_token_budget": 1200,
            },
        }
        return RetrievalOutcome(retrieval_result=retrieval_result, retrieval_debug_meta=debug)

    def _build_retrieval_query(self, *, state) -> tuple[str, dict[str, Any]]:
        """Build normalized retrieval query via operation registry with fallback."""

        payload = {
            "current_message": state.runtime_bundle.get("current_message", ""),
            "context_summary": state.runtime_bundle.get("context_summary", ""),
            "normalized_reasoning_result": {
                "intent": state.normalized_reasoning_result.get("intent", ""),
                "case_slots": state.normalized_reasoning_result.get("case_slots", {}),
                "required_next_slots": state.normalized_reasoning_result.get("required_next_slots", []),
                "is_context_sufficient": state.normalized_reasoning_result.get("is_context_sufficient", False),
                "turn_strategy": state.normalized_reasoning_result.get("turn_strategy", {}),
            },
        }
        try:
            completion = self.llm_gateway.complete(
                operation_key=OperationKey.RETRIEVAL_QUERY_BUILDER,
                turn=state.turn,
                prompt_messages=[
                    {"role": "system", "content": RETRIEVAL_QUERY_BUILDER_SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
            )
            parsed = json.loads(completion.text)
            if isinstance(parsed, dict):
                value = parsed.get("retrieval_query") or parsed.get("query")
                if isinstance(value, str) and value.strip():
                    return value.strip(), {
                        "query_builder_failed": False,
                        "query_builder_error": "",
                    }
        except (LLMGatewayError, json.JSONDecodeError, ValueError, TypeError):
            logger.warning("Step 9 retrieval_query_builder failed; applying fallback query.", exc_info=True)

        fallback = str(state.runtime_bundle.get("current_message", "")).strip()
        return (fallback or "retrieval_no_match_fallback"), {
            "query_builder_failed": True,
            "query_builder_error": "retrieval_query_builder_failed",
        }

    def _load_candidates(self, *, query_vector: list[float]) -> list[dict[str, Any]]:
        """Load enabled candidates and score with dense cosine similarity."""

        rows = self._candidate_queryset()[:30]
        scored: list[dict[str, Any]] = []
        seen_signatures: set[tuple[int, str]] = set()
        for chunk in rows:
            record = getattr(chunk, "embedding_record", None)
            if record is None or not isinstance(record.embedding, list):
                continue
            # Lightweight overlap dedupe by (source, normalized text) before scoring.
            signature = (chunk.source_document_id, chunk.content_text.strip().lower())
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            score = self._cosine(query_vector, [float(item) for item in record.embedding])
            scored.append({"chunk": chunk, "score": score})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:10]

    @staticmethod
    def _candidate_queryset() -> QuerySet[ContentChunk]:
        """Return enabled chunk queryset for retrieval corpus."""

        return ContentChunk.objects.select_related("source_document", "embedding_record").filter(
            state=ContentChunk.STATE_ACTIVE,
            source_document__is_enabled=True,
        )

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        """Compute cosine similarity for two vectors."""

        size = min(len(left), len(right))
        if size == 0:
            return -1.0
        dot = 0.0
        left_norm = 0.0
        right_norm = 0.0
        for index in range(size):
            dot += left[index] * right[index]
            left_norm += left[index] ** 2
            right_norm += right[index] ** 2
        if left_norm == 0 or right_norm == 0:
            return -1.0
        return dot / (sqrt(left_norm) * sqrt(right_norm))

    def _stitch_decision(
        self,
        *,
        state,
        primary_chunk: ContentChunk,
        prev_chunk: ContentChunk | None,
        next_chunk: ContentChunk | None,
    ) -> str:
        """Call stitch validator operation and normalize decision."""
        payload = {
            "primary": {
                "chunk_id": str(primary_chunk.id),
                "source_document_id": str(primary_chunk.source_document_id),
                "segment_index": primary_chunk.segment_index,
                "content_type": primary_chunk.content_type,
                "content_text": primary_chunk.content_text[:600],
            },
            "prev": {
                "chunk_id": str(prev_chunk.id),
                "segment_index": prev_chunk.segment_index,
                "content_text": prev_chunk.content_text[:600],
            }
            if prev_chunk
            else None,
            "next": {
                "chunk_id": str(next_chunk.id),
                "segment_index": next_chunk.segment_index,
                "content_text": next_chunk.content_text[:600],
            }
            if next_chunk
            else None,
        }
        completion = self.llm_gateway.complete(
            operation_key=OperationKey.RETRIEVAL_STITCH_VALIDATOR,
            turn=state.turn,
            prompt_messages=[
                {
                    "role": "system",
                    "content": "Return JSON only: {\"decision\": \"KEEP|STITCH_PREV|STITCH_NEXT|STITCH_BOTH\"}",
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
        )
        parsed = json.loads(completion.text)
        value = parsed.get("decision") if isinstance(parsed, dict) else None
        if value not in {"KEEP", "STITCH_PREV", "STITCH_NEXT", "STITCH_BOTH"}:
            raise ValueError("invalid stitch decision")
        return value

    def _apply_stitch_with_validator(self, *, state, primary_chunk: ContentChunk) -> tuple[list[ContentChunk], str, int]:
        """Iteratively stitch contiguous neighbors with validator decisions."""

        stitched: list[ContentChunk] = [primary_chunk]
        source_id = primary_chunk.source_document_id
        min_index = primary_chunk.segment_index
        max_index = primary_chunk.segment_index
        final_decision = "KEEP"
        calls = 0

        while len(stitched) < 5:
            current_primary = stitched[len(stitched) // 2]
            prev_chunk = (
                ContentChunk.objects.filter(
                    source_document_id=source_id,
                    segment_index=min_index - 1,
                    state=ContentChunk.STATE_ACTIVE,
                )
                .select_related("source_document")
                .first()
            )
            next_chunk = (
                ContentChunk.objects.filter(
                    source_document_id=source_id,
                    segment_index=max_index + 1,
                    state=ContentChunk.STATE_ACTIVE,
                )
                .select_related("source_document")
                .first()
            )
            if prev_chunk is None and next_chunk is None:
                break
            decision = self._stitch_decision(
                state=state,
                primary_chunk=current_primary,
                prev_chunk=prev_chunk,
                next_chunk=next_chunk,
            )
            calls += 1
            final_decision = decision

            if decision == "KEEP":
                break
            if decision in {"STITCH_PREV", "STITCH_BOTH"} and prev_chunk is not None and len(stitched) < 5:
                stitched.insert(0, prev_chunk)
                min_index = prev_chunk.segment_index
            if decision in {"STITCH_NEXT", "STITCH_BOTH"} and next_chunk is not None and len(stitched) < 5:
                stitched.append(next_chunk)
                max_index = next_chunk.segment_index

        return stitched[:5], final_decision, calls
