"""Step 9 knowledge retrieval service for TEACH path."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from math import sqrt
from typing import Any

from django.db.models import QuerySet
from pgvector.django import CosineDistance

from knowledge.models import ChunkEmbedding, ContentChunk
from llm_ops.errors import LLMGatewayError
from llm_ops.gateway import LLMGateway
from runtime.embedding import EmbeddingService, EmbeddingServiceError
from runtime.prompts import RETRIEVAL_QUERY_BUILDER_SYSTEM, RETRIEVAL_STITCH_VALIDATOR_SYSTEM
from runtime.reranker import RerankerClient, RerankerError
from wismo.contracts.enums import OperationKey

logger = logging.getLogger(__name__)

MAX_RETRIEVAL_QUERIES = 3
RERANK_COVERAGE_BONUS_PER_EXTRA_HIT = 0.25
DENSE_COVERAGE_BONUS_PER_EXTRA_HIT = 0.03
DEFAULT_DENSE_POOL_PER_QUERY = 120
MAX_DENSE_POOL_PER_QUERY = 2000


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
            "retrieval_queries": [],
            "query_count": 0,
            "query_embedding_models": [],
            "embedding_failed_query_count": 0,
            "per_query_candidate_count": [],
            "merged_candidate_count": 0,
            "query_embedding_model": "",
            "dense_top_k": 0,
            "reranker_model": os.getenv("WISMO_RERANKER_MODEL", "bge-reranker-v2-m3"),
            "reranker_used": False,
            "reranker_failed": False,
            "reranker_partial_failed": False,
            "reranker_source": "",
            "reranker_gateway_failed": False,
            "reranker_gateway_error": "",
            "reranker_local_failed": False,
            "reranker_local_error": "",
            "reranker_multi_query": True,
            "coverage_bonus_per_extra_hit": RERANK_COVERAGE_BONUS_PER_EXTRA_HIT,
            "fallback_to_prerank": False,
            "stitch_llm_used": False,
            "stitch_llm_calls": 0,
            "stitch_applied": False,
            "retrieval_status": "started",
            "query_builder_failed": False,
        }

        retrieval_queries, query_meta = self._build_retrieval_queries(state=state)
        debug.update(query_meta)
        debug["retrieval_queries"] = retrieval_queries
        debug["query_count"] = len(retrieval_queries)
        debug["retrieval_query"] = retrieval_queries[0] if retrieval_queries else ""

        all_candidates: list[dict[str, Any]] = []
        query_models: list[str] = []
        for query in retrieval_queries:
            try:
                query_vector, embedding_meta = self.embedding_service.embed_query(query=query, turn=state.turn)
                model_name = str(embedding_meta.get("query_embedding_model", "")).strip()
                if model_name:
                    query_models.append(model_name)
            except EmbeddingServiceError:
                logger.warning("Step 9 embedding failed for one retrieval query.", exc_info=True)
                debug["embedding_failed_query_count"] += 1
                debug["per_query_candidate_count"].append(0)
                continue
            query_candidates = self._load_candidates(query_vector=query_vector)
            debug["per_query_candidate_count"].append(len(query_candidates))
            for candidate in query_candidates:
                all_candidates.append(
                    {
                        "query": query,
                        "chunk": candidate["chunk"],
                        "score": candidate["score"],
                    }
                )

        if query_models:
            debug["query_embedding_models"] = query_models
            debug["query_embedding_model"] = query_models[0]

        if not all_candidates:
            if debug["embedding_failed_query_count"] > 0:
                logger.warning("Step 9 embedding failed across all retrieval queries.")
                debug["retrieval_status"] = "embedding_failed"
                return RetrievalOutcome(retrieval_result=None, retrieval_debug_meta=debug)
            logger.warning("Step 9 retrieval found no enabled candidates.")
            debug["retrieval_status"] = "empty_or_failed"
            return RetrievalOutcome(retrieval_result=None, retrieval_debug_meta=debug)

        candidates = self._merge_candidates(all_candidates=all_candidates)
        debug["merged_candidate_count"] = len(candidates)
        debug["dense_top_k"] = len(candidates)

        reranked = candidates
        rerank_score_by_id: dict[str, float] = {}
        rerank_coverage_by_id: dict[str, int] = {}
        rerank_failures = 0
        rerank_sources: set[str] = set()
        rerank_candidates = [{"chunk_id": str(item["chunk"].id), "text": item["chunk"].content_text} for item in candidates]
        for query in retrieval_queries:
            try:
                ranked_ids = self.reranker_client.rerank(
                    query=query,
                    candidates=rerank_candidates,
                    turn=state.turn,
                )
            except (RerankerError, ValueError):
                rerank_failures += 1
                run_meta = getattr(self.reranker_client, "last_run_meta", None)
                if isinstance(run_meta, dict):
                    if run_meta.get("gateway_failed"):
                        debug["reranker_gateway_failed"] = True
                        if not debug["reranker_gateway_error"]:
                            debug["reranker_gateway_error"] = str(run_meta.get("gateway_error", ""))
                    if run_meta.get("local_failed"):
                        debug["reranker_local_failed"] = True
                        if not debug["reranker_local_error"]:
                            debug["reranker_local_error"] = str(run_meta.get("local_error", ""))
                continue
            run_meta = getattr(self.reranker_client, "last_run_meta", None)
            if isinstance(run_meta, dict):
                source = str(run_meta.get("source", "")).strip()
                if source:
                    rerank_sources.add(source)
                if run_meta.get("gateway_failed"):
                    debug["reranker_gateway_failed"] = True
                    if not debug["reranker_gateway_error"]:
                        debug["reranker_gateway_error"] = str(run_meta.get("gateway_error", ""))
                if run_meta.get("local_failed"):
                    debug["reranker_local_failed"] = True
                    if not debug["reranker_local_error"]:
                        debug["reranker_local_error"] = str(run_meta.get("local_error", ""))
            for index, chunk_id in enumerate(ranked_ids):
                score = float(len(ranked_ids) - index)
                previous = rerank_score_by_id.get(chunk_id, 0.0)
                if score > previous:
                    rerank_score_by_id[chunk_id] = score
                rerank_coverage_by_id[chunk_id] = rerank_coverage_by_id.get(chunk_id, 0) + 1

        if rerank_score_by_id:
            reranked = self._sort_with_rerank_scores(
                candidates=candidates,
                rerank_score_by_id=rerank_score_by_id,
                rerank_coverage_by_id=rerank_coverage_by_id,
            )
            debug["reranker_used"] = True
            if len(rerank_sources) == 1:
                debug["reranker_source"] = next(iter(rerank_sources))
            elif len(rerank_sources) > 1:
                debug["reranker_source"] = "mixed"
        else:
            logger.warning("Step 9 reranker failed; fallback to prerank ordering.")
            debug["reranker_failed"] = True
            debug["fallback_to_prerank"] = True
            debug["reranker_source"] = "prerank"
            reranked = sorted(
                candidates,
                key=lambda item: (
                    item["score"] + DENSE_COVERAGE_BONUS_PER_EXTRA_HIT * max(0, int(item.get("coverage_hits", 1)) - 1),
                    item["score"],
                ),
                reverse=True,
            )
        if rerank_failures > 0 and rerank_failures < len(retrieval_queries):
            debug["reranker_partial_failed"] = True
        if rerank_failures >= len(retrieval_queries):
            debug["reranker_failed"] = True

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
            "rerank_score": primary.get("rerank_score") or rerank_score_by_id.get(str(primary["chunk"].id)),
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

    def _build_retrieval_queries(self, *, state) -> tuple[list[str], dict[str, Any]]:
        """Build normalized retrieval queries via operation registry with fallback."""

        payload = {
            "current_message": state.runtime_bundle.get("current_message", ""),
            "context_summary": state.runtime_bundle.get("context_summary", ""),
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
                normalized = self._normalize_retrieval_queries(
                    parsed.get("retrieval_queries")
                    if parsed.get("retrieval_queries") is not None
                    else (parsed.get("retrieval_query") or parsed.get("query"))
                )
                if normalized:
                    return normalized, {
                        "query_builder_failed": False,
                        "query_builder_error": "",
                    }
        except (LLMGatewayError, json.JSONDecodeError, ValueError, TypeError):
            logger.warning("Step 9 retrieval_query_builder failed; applying fallback query.", exc_info=True)

        fallback = str(state.runtime_bundle.get("current_message", "")).strip()
        return self._normalize_retrieval_queries(fallback or "retrieval_no_match_fallback"), {
            "query_builder_failed": True,
            "query_builder_error": "retrieval_query_builder_failed",
        }

    @staticmethod
    def _normalize_retrieval_queries(value: object) -> list[str]:
        if isinstance(value, str):
            normalized = [value.strip()]
        elif isinstance(value, list):
            normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        else:
            normalized = []
        deduped: list[str] = []
        for item in normalized:
            if item not in deduped:
                deduped.append(item[:300])
        return deduped[:MAX_RETRIEVAL_QUERIES]

    @staticmethod
    def _merge_candidates(*, all_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for item in all_candidates:
            chunk = item["chunk"]
            chunk_id = str(chunk.id)
            dense_score = float(item["score"])
            query = str(item.get("query", ""))
            existing = merged.get(chunk_id)
            if existing is None:
                merged[chunk_id] = {
                    "chunk": chunk,
                    "score": dense_score,
                    "matched_queries": {query} if query else set(),
                    "coverage_hits": 1,
                }
                continue
            existing["score"] = max(float(existing["score"]), dense_score)
            if query:
                existing["matched_queries"].add(query)
                existing["coverage_hits"] = len(existing["matched_queries"])
        return sorted(merged.values(), key=lambda item: item["score"], reverse=True)

    @staticmethod
    def _sort_with_rerank_scores(
        *,
        candidates: list[dict[str, Any]],
        rerank_score_by_id: dict[str, float],
        rerank_coverage_by_id: dict[str, int],
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for item in candidates:
            chunk_id = str(item["chunk"].id)
            base = rerank_score_by_id.get(chunk_id, 0.0)
            coverage = rerank_coverage_by_id.get(chunk_id, 0)
            final = base + RERANK_COVERAGE_BONUS_PER_EXTRA_HIT * max(0, coverage - 1)
            enriched.append(
                {
                    **item,
                    "rerank_score": final,
                    "rerank_coverage_hits": coverage,
                }
            )
        return sorted(enriched, key=lambda item: (item["rerank_score"], item["score"]), reverse=True)

    def _load_candidates(self, *, query_vector: list[float]) -> list[dict[str, Any]]:
        """Load enabled candidates and score with dense cosine similarity."""

        pool_limit = self._dense_candidate_pool_limit()
        ann_candidates = self._load_candidates_via_ann(query_vector=query_vector, pool_limit=pool_limit)
        if ann_candidates:
            return ann_candidates
        return self._load_candidates_via_python_cosine(query_vector=query_vector, pool_limit=pool_limit)

    def _load_candidates_via_ann(self, *, query_vector: list[float], pool_limit: int) -> list[dict[str, Any]]:
        """Load candidates using ANN on embeddings first, then join metadata."""

        try:
            ann_rows = list(
                ChunkEmbedding.objects.annotate(
                    distance=CosineDistance("embedding", query_vector)
                )
                .order_by("distance")
                .values_list("chunk_id", "distance")[:pool_limit]
            )
        except Exception:
            logger.warning(
                "Step 9 ANN-first retrieval failed; fallback to python cosine scoring.",
                exc_info=True,
            )
            return []

        if not ann_rows:
            return []

        chunk_ids = [row[0] for row in ann_rows]
        chunk_by_id = {
            chunk.id: chunk
            for chunk in self._candidate_queryset().filter(id__in=chunk_ids)
        }

        scored: list[dict[str, Any]] = []
        seen_signatures: set[tuple[int, str]] = set()
        for chunk_id, distance in ann_rows:
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            # Lightweight overlap dedupe by (source, normalized text) before scoring.
            signature = (chunk.source_document_id, chunk.content_text.strip().lower())
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            score = 1.0 - float(distance)
            scored.append({"chunk": chunk, "score": score})

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:10]

    def _load_candidates_via_python_cosine(self, *, query_vector: list[float], pool_limit: int) -> list[dict[str, Any]]:
        """Fallback dense retrieval path when ANN-first query is unavailable."""

        rows = self._candidate_queryset()
        if hasattr(rows, "__getitem__"):
            rows = rows[:pool_limit]

        scored: list[dict[str, Any]] = []
        seen_signatures: set[tuple[int, str]] = set()
        for chunk in rows:
            record = getattr(chunk, "embedding_record", None)
            if record is None:
                continue
            embedding_vector = self._coerce_embedding_vector(getattr(record, "embedding", None))
            if embedding_vector is None:
                continue
            # Lightweight overlap dedupe by (source, normalized text) before scoring.
            signature = (chunk.source_document_id, chunk.content_text.strip().lower())
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            score = self._cosine(query_vector, embedding_vector)
            scored.append({"chunk": chunk, "score": score})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:10]

    @staticmethod
    def _coerce_embedding_vector(value: object) -> list[float] | None:
        """Normalize vector payload from storage into a numeric list."""

        if value is None:
            return None

        raw = value.tolist() if hasattr(value, "tolist") and callable(getattr(value, "tolist")) else value
        if isinstance(raw, (str, bytes)):
            return None
        if not isinstance(raw, (list, tuple)):
            return None

        vector: list[float] = []
        for item in raw:
            try:
                vector.append(float(item))
            except (TypeError, ValueError):
                return None
        return vector

    @staticmethod
    def _candidate_queryset() -> QuerySet[ContentChunk]:
        """Return enabled chunk queryset for retrieval corpus."""

        return ContentChunk.objects.select_related("source_document", "embedding_record").filter(
            state=ContentChunk.STATE_ACTIVE,
            source_document__is_enabled=True,
            embedding_record__isnull=False,
        )

    @staticmethod
    def _dense_candidate_pool_limit() -> int:
        """Return per-query dense pool limit with bounded env override."""

        raw = os.getenv("WISMO_RETRIEVAL_DENSE_POOL_PER_QUERY", str(DEFAULT_DENSE_POOL_PER_QUERY))
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_DENSE_POOL_PER_QUERY
        if value <= 0:
            return DEFAULT_DENSE_POOL_PER_QUERY
        return min(value, MAX_DENSE_POOL_PER_QUERY)

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
                    "content": RETRIEVAL_STITCH_VALIDATOR_SYSTEM,
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
