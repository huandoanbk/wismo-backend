"""Reranker clients for Step 9 shortlist scoring with gateway-first fallback chain."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

from llm_ops.errors import LLMGatewayError
from llm_ops.gateway import LLMGateway
from wismo.contracts.enums import OperationKey


class RerankerError(Exception):
    """Raised when reranker call cannot provide usable ranking."""


@dataclass(frozen=True)
class RerankerRunMeta:
    """One reranker attempt summary for retrieval debug metadata."""

    source: str
    gateway_failed: bool = False
    gateway_error: str = ""
    local_failed: bool = False
    local_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for runtime debug payloads."""

        return {
            "source": self.source,
            "gateway_failed": self.gateway_failed,
            "gateway_error": self.gateway_error,
            "local_failed": self.local_failed,
            "local_error": self.local_error,
        }


class RerankerClient:
    """HTTP client for local bge-reranker-v2-m3 style ranking services."""

    def __init__(self) -> None:
        self.last_run_meta: dict[str, Any] = {}

    def rerank(self, *, query: str, candidates: list[dict[str, str]], turn=None) -> list[str]:
        """Return ranked chunk ids ordered best-to-worst."""

        _ = turn
        enabled = os.getenv("WISMO_RERANKER_ENABLED", "true").lower() == "true"
        if not enabled:
            raise RerankerError("reranker_disabled")

        endpoint = os.getenv("WISMO_RERANKER_ENDPOINT", "").strip()
        if not endpoint:
            raise RerankerError("reranker_endpoint_missing")

        timeout_ms = int(os.getenv("WISMO_RERANKER_TIMEOUT_MS", "2000"))
        try:
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
        except (requests.RequestException, ConnectionError) as exc:
            raise RerankerError("reranker_request_failed") from exc

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
                try:
                    pairs.append((str(chunk_id), float(score)))
                except (TypeError, ValueError):
                    continue
            if pairs:
                pairs.sort(key=lambda pair: pair[1], reverse=True)
                return [chunk_id for chunk_id, _score in pairs]

        raise RerankerError("reranker_payload_invalid")


class GatewayRerankerClient:
    """LLM-gateway-backed reranker client for external providers like DeepInfra."""

    def __init__(self, llm_gateway: LLMGateway) -> None:
        self.llm_gateway = llm_gateway
        self.last_run_meta: dict[str, Any] = {}

    def rerank(self, *, query: str, candidates: list[dict[str, str]], turn=None) -> list[str]:
        """Rerank candidates via OperationKey.RETRIEVAL_RERANKER gateway operation."""

        if turn is None:
            raise RerankerError("reranker_gateway_turn_missing")
        completion = self.llm_gateway.complete(
            operation_key=OperationKey.RETRIEVAL_RERANKER,
            turn=turn,
            prompt_messages=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "query": query,
                            "candidates": candidates,
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        )
        try:
            parsed = json.loads(completion.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise RerankerError("reranker_gateway_payload_invalid") from exc
        scores = parsed.get("scores") if isinstance(parsed, dict) else None
        if not isinstance(scores, list) or len(scores) != len(candidates):
            raise RerankerError("reranker_gateway_scores_invalid")

        pairs: list[tuple[str, float]] = []
        for index, score in enumerate(scores):
            try:
                pairs.append((str(candidates[index].get("chunk_id")), float(score)))
            except (TypeError, ValueError) as exc:
                raise RerankerError("reranker_gateway_scores_invalid") from exc
        pairs.sort(key=lambda pair: pair[1], reverse=True)
        ranked = [chunk_id for chunk_id, _score in pairs if chunk_id]
        if not ranked:
            raise RerankerError("reranker_gateway_scores_invalid")
        return ranked


class CompositeRerankerClient(RerankerClient):
    """Gateway-first reranker with local HTTP fallback."""

    def __init__(self, *, llm_gateway: LLMGateway, local_client: RerankerClient | None = None) -> None:
        super().__init__()
        self.gateway_client = GatewayRerankerClient(llm_gateway=llm_gateway)
        self.local_client = local_client or RerankerClient()
        self.gateway_enabled = os.getenv("WISMO_RERANKER_GATEWAY_ENABLED", "true").lower() == "true"

    def rerank(self, *, query: str, candidates: list[dict[str, str]], turn=None) -> list[str]:
        """Try gateway reranker first, then fallback to local HTTP reranker."""

        if self.gateway_enabled:
            try:
                ranked = self.gateway_client.rerank(query=query, candidates=candidates, turn=turn)
                self.last_run_meta = RerankerRunMeta(source="gateway").as_dict()
                return ranked
            except (RerankerError, LLMGatewayError) as exc:
                gateway_error = str(exc)
            except Exception as exc:  # pragma: no cover - defensive fallback path
                gateway_error = exc.__class__.__name__
        else:
            gateway_error = "reranker_gateway_disabled"

        try:
            ranked = self.local_client.rerank(query=query, candidates=candidates, turn=turn)
            self.last_run_meta = RerankerRunMeta(
                source="local",
                gateway_failed=True,
                gateway_error=gateway_error,
            ).as_dict()
            return ranked
        except RerankerError as local_exc:
            self.last_run_meta = RerankerRunMeta(
                source="prerank",
                gateway_failed=True,
                gateway_error=gateway_error,
                local_failed=True,
                local_error=str(local_exc),
            ).as_dict()
            raise
