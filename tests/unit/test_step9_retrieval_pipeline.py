"""Unit tests for Main Flow Step 9 retrieval pipeline."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from llm_ops.errors import LLMGatewayProviderError
from runtime.embedding import EmbeddingService, EmbeddingServiceError
from runtime.orchestrator import RuntimeOrchestrator, RuntimeState
from runtime.reranker import RerankerClient, RerankerError
from runtime.retrieval import KnowledgeRetrievalService
from wismo.contracts.enums import OperationKey, ResponseMethod


class DummyGateway:
    """Minimal gateway stub for retrieval unit tests."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def complete(self, *, operation_key, turn, prompt_messages):  # noqa: D401
        self.calls.append(
            {
                "operation_key": operation_key,
                "turn": turn,
                "prompt_messages": prompt_messages,
            }
        )
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(text=value)


def _state_for_step9() -> RuntimeState:
    return RuntimeState(
        request_payload=SimpleNamespace(message="hello"),
        identity=SimpleNamespace(owner_kwargs=lambda: {}),
        quota_window=SimpleNamespace(),
        turn=SimpleNamespace(id="turn-1"),
        runtime_bundle={
            "current_message": "hello",
            "context_summary": "summary",
            "reasoning_result": {},
        },
        response_method=ResponseMethod.ASK,
        retrieval_required=False,
        final_safety_state="normal",
    )


def test_step9_gate_skip_when_not_teach() -> None:
    orchestrator = RuntimeOrchestrator(llm_gateway=DummyGateway([]))
    state = _state_for_step9()
    state.response_method = ResponseMethod.ASK

    orchestrator._knowledge_retrieval(state)

    assert state.runtime_bundle["retrieval_result"] is None
    assert state.runtime_bundle["retrieval_debug_meta"]["retrieval_status"] == "skipped"


def test_step9_gate_run_uses_retrieval_service_outcome() -> None:
    orchestrator = RuntimeOrchestrator(llm_gateway=DummyGateway([]))
    state = _state_for_step9()
    state.response_method = ResponseMethod.TEACH
    state.retrieval_required = True

    orchestrator.retrieval_service.run = lambda state: SimpleNamespace(  # type: ignore[assignment]
        retrieval_result={"primary_chunk_id": "1"},
        retrieval_debug_meta={"retrieval_status": "ok"},
    )

    orchestrator._knowledge_retrieval(state)

    assert state.runtime_bundle["retrieval_result"]["primary_chunk_id"] == "1"
    assert state.runtime_bundle["retrieval_debug_meta"]["retrieval_status"] == "ok"


def test_embedding_service_gateway_fail_local_success() -> None:
    gateway = DummyGateway([LLMGatewayProviderError()])
    service = EmbeddingService(gateway)

    with patch("runtime.embedding.requests.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        mock_post.return_value.json.return_value = {"embedding": [0.1, 0.2]}
        with patch.dict("os.environ", {"WISMO_EMBEDDING_ENDPOINT": "http://embed.local"}):
            vector, meta = service.embed_query(query="q", turn=SimpleNamespace())

    assert vector == [0.1, 0.2]
    assert meta["embedding_via_local"] is True
    assert meta["embedding_gateway_failed"] is True


def test_embedding_service_dual_path_failure_raises() -> None:
    gateway = DummyGateway([LLMGatewayProviderError()])
    service = EmbeddingService(gateway)

    with patch("runtime.embedding.requests.post", side_effect=RuntimeError("down")):
        with patch.dict("os.environ", {"WISMO_EMBEDDING_ENDPOINT": "http://embed.local"}):
            with pytest.raises(EmbeddingServiceError):
                service.embed_query(query="q", turn=SimpleNamespace())


def test_reranker_client_parses_scores_payload() -> None:
    client = RerankerClient()

    with patch("runtime.reranker.requests.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        mock_post.return_value.json.return_value = {
            "scores": [
                {"chunk_id": "b", "score": 0.1},
                {"chunk_id": "a", "score": 0.9},
            ]
        }
        with patch.dict(
            "os.environ",
            {
                "WISMO_RERANKER_ENABLED": "true",
                "WISMO_RERANKER_ENDPOINT": "http://reranker.local/rerank",
            },
        ):
            ranked_ids = client.rerank(query="q", candidates=[{"chunk_id": "a", "text": "A"}])

    assert ranked_ids == ["a", "b"]


def test_retrieval_service_reranker_failure_fallback_prerank() -> None:
    gateway = DummyGateway([
        json.dumps({"retrieval_query": "query"}),
    ])
    embedding = SimpleNamespace(embed_query=lambda query, turn: ([1.0, 0.0], {"query_embedding_model": "local"}))
    reranker = SimpleNamespace(rerank=lambda query, candidates: (_ for _ in ()).throw(RerankerError("boom")))
    service = KnowledgeRetrievalService(
        llm_gateway=gateway,
        embedding_service=embedding,
        reranker_client=reranker,
    )

    source = SimpleNamespace(
        id=uuid.uuid4(),
        title="T",
        speaker_or_author="A",
        source_type="talk",
    )
    chunk = SimpleNamespace(
        id=uuid.uuid4(),
        source_document=source,
        source_document_id=source.id,
        segment_index=1,
        content_text="chunk-text",
        content_type="story",
        topic="x",
        dharma_concepts=["mind"],
    )

    service._load_candidates = lambda query_vector: [{"chunk": chunk, "score": 0.8}]  # type: ignore[assignment]
    service._apply_stitch_with_validator = lambda state, primary_chunk: ([primary_chunk], "KEEP", 1)  # type: ignore[assignment]

    state = SimpleNamespace(
        turn=SimpleNamespace(id="t"),
        runtime_bundle={"current_message": "hello", "context_summary": "sum"},
        normalized_reasoning_result={
            "intent": "ask_teaching_or_perspective",
            "case_slots": {},
            "required_next_slots": [],
            "is_context_sufficient": True,
            "turn_strategy": {},
        },
    )

    outcome = service.run(state=state)

    assert outcome.retrieval_result is not None
    assert outcome.retrieval_result["primary_chunk_id"] == str(chunk.id)
    assert outcome.retrieval_result["rerank_score"] is None
    assert outcome.retrieval_debug_meta["reranker_failed"] is True
    assert outcome.retrieval_debug_meta["fallback_to_prerank"] is True
    assert "sparse_top_k" not in outcome.retrieval_debug_meta
    assert "fused_top_k" not in outcome.retrieval_debug_meta


def test_retrieval_service_query_builder_uses_operation_registry() -> None:
    gateway = DummyGateway([json.dumps({"retrieval_query": "q"})])
    service = KnowledgeRetrievalService(
        llm_gateway=gateway,
        embedding_service=SimpleNamespace(embed_query=lambda query, turn: ([1.0], {})),
        reranker_client=SimpleNamespace(rerank=lambda query, candidates: []),
    )
    state = SimpleNamespace(
        turn=SimpleNamespace(id="t"),
        runtime_bundle={"current_message": "hello", "context_summary": "sum"},
        normalized_reasoning_result={
            "intent": "unclear",
            "case_slots": {},
            "required_next_slots": [],
            "is_context_sufficient": False,
            "turn_strategy": {},
        },
    )

    value, meta = service._build_retrieval_query(state=state)

    assert value == "q"
    assert meta["query_builder_failed"] is False
    assert gateway.calls[0]["operation_key"] == OperationKey.RETRIEVAL_QUERY_BUILDER


def test_retrieval_service_query_builder_fallback_marks_error() -> None:
    gateway = DummyGateway([LLMGatewayProviderError()])
    service = KnowledgeRetrievalService(
        llm_gateway=gateway,
        embedding_service=SimpleNamespace(embed_query=lambda query, turn: ([1.0], {})),
        reranker_client=SimpleNamespace(rerank=lambda query, candidates: []),
    )
    state = SimpleNamespace(
        turn=SimpleNamespace(id="t"),
        runtime_bundle={"current_message": ""},
        normalized_reasoning_result={},
    )

    value, meta = service._build_retrieval_query(state=state)

    assert value == "retrieval_no_match_fallback"
    assert meta["query_builder_failed"] is True
