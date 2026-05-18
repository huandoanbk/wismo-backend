"""Embedding service for Step 9 retrieval query vectorization."""

from __future__ import annotations

import json
import os
from typing import Any

import requests

from llm_ops.errors import LLMGatewayError
from llm_ops.gateway import LLMGateway
from runtime.prompts import RETRIEVAL_QUERY_EMBEDDING_SYSTEM
from wismo.contracts.enums import OperationKey


class EmbeddingServiceError(Exception):
    """Raised when query embedding is unavailable across all paths."""


class EmbeddingService:
    """Resolve query embeddings via gateway-first then local HTTP fallback."""

    def __init__(self, llm_gateway: LLMGateway) -> None:
        self.llm_gateway = llm_gateway

    def embed_query(self, *, query: str, turn) -> tuple[list[float], dict[str, Any]]:
        """Return query embedding vector and debug metadata."""

        debug_meta: dict[str, Any] = {
            "embedding_via_gateway": False,
            "embedding_via_local": False,
            "embedding_gateway_failed": False,
            "embedding_local_failed": False,
            "query_embedding_model": "",
        }

        try:
            vector = self._embed_via_gateway(query=query, turn=turn)
            debug_meta["embedding_via_gateway"] = True
            debug_meta["query_embedding_model"] = "gateway"
            return vector, debug_meta
        except (LLMGatewayError, ValueError, TypeError, json.JSONDecodeError):
            debug_meta["embedding_gateway_failed"] = True

        try:
            vector = self._embed_via_local(query=query)
            debug_meta["embedding_via_local"] = True
            debug_meta["query_embedding_model"] = os.getenv("WISMO_EMBEDDING_MODEL", "local")
            return vector, debug_meta
        except (requests.RequestException, ValueError, TypeError, RuntimeError):
            debug_meta["embedding_local_failed"] = True

        raise EmbeddingServiceError(json.dumps(debug_meta))

    def _embed_via_gateway(self, *, query: str, turn) -> list[float]:
        completion = self.llm_gateway.complete(
            operation_key=OperationKey.RETRIEVAL_QUERY_EMBEDDING,
            turn=turn,
            prompt_messages=[
                {
                    "role": "system",
                    "content": RETRIEVAL_QUERY_EMBEDDING_SYSTEM,
                },
                {
                    "role": "user",
                    "content": json.dumps({"query": query}, ensure_ascii=False),
                },
            ],
        )
        payload = json.loads(completion.text)
        embedding = payload.get("embedding") if isinstance(payload, dict) else None
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("invalid embedding payload")
        return [float(item) for item in embedding]

    @staticmethod
    def _embed_via_local(*, query: str) -> list[float]:
        endpoint = os.getenv("WISMO_EMBEDDING_ENDPOINT", "").strip()
        if not endpoint:
            raise ValueError("WISMO_EMBEDDING_ENDPOINT is empty")

        timeout_ms = int(os.getenv("WISMO_EMBEDDING_TIMEOUT_MS", "2000"))
        response = requests.post(
            endpoint,
            json={
                "text": query,
                "model": os.getenv("WISMO_EMBEDDING_MODEL", ""),
            },
            timeout=max(0.1, timeout_ms / 1000),
        )
        response.raise_for_status()
        payload = response.json()
        embedding = payload.get("embedding") or payload.get("vector")
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("invalid local embedding payload")
        return [float(item) for item in embedding]
