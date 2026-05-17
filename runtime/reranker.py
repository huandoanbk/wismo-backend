"""Reranker client for Step 9 retrieval shortlist scoring."""

from __future__ import annotations

import os
from typing import Any

import requests


class RerankerError(Exception):
    """Raised when reranker call cannot provide usable ranking."""


class RerankerClient:
    """HTTP client for bge-reranker-v2-m3 style ranking services."""

    def rerank(self, *, query: str, candidates: list[dict[str, str]]) -> list[str]:
        """Return ranked chunk ids ordered best-to-worst."""

        enabled = os.getenv("WISMO_RERANKER_ENABLED", "true").lower() == "true"
        if not enabled:
            raise RerankerError("reranker_disabled")

        endpoint = os.getenv("WISMO_RERANKER_ENDPOINT", "").strip()
        if not endpoint:
            raise RerankerError("reranker_endpoint_missing")

        timeout_ms = int(os.getenv("WISMO_RERANKER_TIMEOUT_MS", "2000"))
        response = requests.post(
            endpoint,
            json={
                "query": query,
                "candidates": candidates,
                "model": os.getenv("WISMO_RERANKER_MODEL", "bge-reranker-v2-m3"),
            },
            timeout=max(0.1, timeout_ms / 1000),
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()

        ranked_ids = payload.get("ranked_ids")
        if isinstance(ranked_ids, list) and ranked_ids:
            return [str(item) for item in ranked_ids]

        scores = payload.get("scores")
        if isinstance(scores, list) and scores:
            pairs: list[tuple[str, float]] = []
            for item in scores:
                if not isinstance(item, dict):
                    continue
                chunk_id = item.get("chunk_id")
                score = item.get("score")
                if chunk_id is None or score is None:
                    continue
                pairs.append((str(chunk_id), float(score)))
            if pairs:
                pairs.sort(key=lambda pair: pair[1], reverse=True)
                return [chunk_id for chunk_id, _score in pairs]

        raise RerankerError("reranker_payload_invalid")
