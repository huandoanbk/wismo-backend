"""Branch tests for Steps 9/10/11/12 — covering gaps not in existing unit tests.

Step 9:  9.8 stitch LLM fail → fallback; 9.5A stitch decision branches
Step 10: 10.7.1 LISTEN fallback defaults; 10.7.2 REFLECT omits missing fields;
         10.7.3 FOLLOWUP tiers (has strategy, has summary only, has neither)
Step 12: 12.4 quota_exhausted_after_turn=True when quota already exhausted
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from accounts.models import GuestIdentity
from chat.models import Case, Chat, ChatTurn
from llm_ops.errors import LLMGatewayError
from runtime.finalization import PostTurnFinalizationService
from runtime.models import UsageQuotaWindow
from runtime.orchestrator import RuntimeState
from runtime.prompt_assembly import PromptAssemblyService
from runtime.retrieval import KnowledgeRetrievalService
from runtime.services import IdentityStateStoreService, QuotaService
from wismo.contracts.enums import OperationKey, ResponseMethod

# ── shared helpers ────────────────────────────────────────────────


class _DummyGateway:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses

    def complete(self, *, operation_key, turn, prompt_messages):
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(text=value)


def _chunk_ns(seg_idx: int, source_id: uuid.UUID | None = None) -> SimpleNamespace:
    """SimpleNamespace that looks enough like a ContentChunk for stitch logic."""
    sid = source_id or uuid.uuid4()
    return SimpleNamespace(
        id=uuid.uuid4(),
        source_document_id=sid,
        segment_index=seg_idx,
        content_text=f"text-{seg_idx}",
        content_type="story",
        topic="topic",
        dharma_concepts=[],
        is_enabled=True,
        source_document=SimpleNamespace(
            id=sid, title="T", speaker_or_author="A", source_type="talk"
        ),
    )


def _patch_chunk_objects(chunks_by_index: dict[int, SimpleNamespace | None]):
    """Return mock for ContentChunk.objects where filter(segment_index=i) → chunks_by_index[i]."""
    def _filter(**kwargs):
        idx = kwargs.get("segment_index")
        result = chunks_by_index.get(idx)
        mock_qs = MagicMock()
        mock_qs.select_related.return_value.first.return_value = result
        return mock_qs

    mock_objects = MagicMock()
    mock_objects.filter.side_effect = _filter
    return mock_objects


def _service() -> KnowledgeRetrievalService:
    return KnowledgeRetrievalService(
        llm_gateway=_DummyGateway([]),
        embedding_service=SimpleNamespace(embed_query=lambda query, turn: ([1.0], {})),
        reranker_client=SimpleNamespace(rerank=lambda query, candidates, turn=None: []),
    )


def _state_for_stitch() -> SimpleNamespace:
    return SimpleNamespace(
        turn=SimpleNamespace(id="t"),
        runtime_bundle={"current_message": "hello", "context_summary": ""},
        normalized_reasoning_result={
            "intent": "ask_teaching_or_perspective",
            "case_slots": {},
            "required_next_slots": [],
            "is_context_sufficient": True,
            "turn_strategy": {},
        },
    )


# ══════════════════════════════════════════════════════════════════
#  STEP 9 — 9.8: stitch LLM fail → fallback to primary chunk
# ══════════════════════════════════════════════════════════════════


def test_step9_stitch_llm_fail_fallback_to_primary_chunk() -> None:
    """9.8: stitch confirm mini-LLM fail → skip stitch, use primary chunk, still returns result."""
    source_id = uuid.uuid4()
    primary = _chunk_ns(5, source_id)

    service = _service()
    service._build_retrieval_queries = lambda state: (["query"], {})  # type: ignore[assignment]
    service._load_candidates = lambda query_vector: [{"chunk": primary, "score": 0.9}]  # type: ignore[assignment]

    def _raise_stitch(*args, **kwargs):
        raise LLMGatewayError(code="ERR", status_code=500)

    service._apply_stitch_with_validator = _raise_stitch  # type: ignore[assignment]

    state = _state_for_stitch()
    outcome = service.run(state=state)

    assert outcome.retrieval_result is not None
    assert outcome.retrieval_result["primary_chunk_id"] == str(primary.id)
    assert outcome.retrieval_debug_meta["stitch_applied"] is False


# ══════════════════════════════════════════════════════════════════
#  STEP 9 — 9.5A: stitch decision branches
# ══════════════════════════════════════════════════════════════════


def test_step9_stitch_no_neighbors_stops_immediately() -> None:
    """9.5A: no prev or next chunk → loop exits before calling validator."""
    source_id = uuid.uuid4()
    primary = _chunk_ns(5, source_id)
    service = _service()
    state = _state_for_stitch()

    mock_objects = _patch_chunk_objects({4: None, 6: None})

    with patch("runtime.retrieval.ContentChunk.objects", mock_objects):
        stitched, decision, calls = service._apply_stitch_with_validator(
            state=state, primary_chunk=primary
        )

    assert stitched == [primary]
    assert decision == "KEEP"
    assert calls == 0


def test_step9_stitch_keep_returns_single_chunk() -> None:
    """9.5A KEEP: validator returns KEEP → stops, single chunk returned."""
    source_id = uuid.uuid4()
    primary = _chunk_ns(5, source_id)
    prev_chunk = _chunk_ns(4, source_id)
    next_chunk = _chunk_ns(6, source_id)
    service = _service()
    state = _state_for_stitch()

    mock_objects = _patch_chunk_objects({4: prev_chunk, 6: next_chunk})

    with patch("runtime.retrieval.ContentChunk.objects", mock_objects):
        with patch.object(service, "_stitch_decision", return_value="KEEP"):
            stitched, decision, calls = service._apply_stitch_with_validator(
                state=state, primary_chunk=primary
            )

    assert stitched == [primary]
    assert decision == "KEEP"
    assert calls == 1


def test_step9_stitch_prev_prepends_prev_chunk() -> None:
    """9.5A STITCH_PREV: validator returns STITCH_PREV → prev chunk prepended."""
    source_id = uuid.uuid4()
    primary = _chunk_ns(5, source_id)
    prev_chunk = _chunk_ns(4, source_id)
    service = _service()
    state = _state_for_stitch()

    # Only next iteration has no neighbors → stops after 2nd call
    decisions = ["STITCH_PREV", "KEEP"]
    mock_objects = _patch_chunk_objects({3: None, 4: prev_chunk, 6: None})

    with patch("runtime.retrieval.ContentChunk.objects", mock_objects):
        with patch.object(service, "_stitch_decision", side_effect=decisions):
            stitched, decision, calls = service._apply_stitch_with_validator(
                state=state, primary_chunk=primary
            )

    assert len(stitched) == 2
    assert stitched[0] == prev_chunk
    assert stitched[1] == primary
    assert calls == 1  # after STITCH_PREV, no more neighbors → loop exits without 2nd call


def test_step9_stitch_next_appends_next_chunk() -> None:
    """9.5A STITCH_NEXT: validator returns STITCH_NEXT → next chunk appended."""
    source_id = uuid.uuid4()
    primary = _chunk_ns(5, source_id)
    next_chunk = _chunk_ns(6, source_id)
    service = _service()
    state = _state_for_stitch()

    decisions = ["STITCH_NEXT", "KEEP"]
    mock_objects = _patch_chunk_objects({4: None, 6: next_chunk, 7: None})

    with patch("runtime.retrieval.ContentChunk.objects", mock_objects):
        with patch.object(service, "_stitch_decision", side_effect=decisions):
            stitched, decision, calls = service._apply_stitch_with_validator(
                state=state, primary_chunk=primary
            )

    assert len(stitched) == 2
    assert stitched[-1] == next_chunk
    assert calls == 1  # after STITCH_NEXT, no more neighbors → loop exits without 2nd call


def test_step9_stitch_both_adds_prev_and_next() -> None:
    """9.5A STITCH_BOTH: validator returns STITCH_BOTH → both neighbors added, then no more."""
    source_id = uuid.uuid4()
    primary = _chunk_ns(5, source_id)
    prev_chunk = _chunk_ns(4, source_id)
    next_chunk = _chunk_ns(6, source_id)
    service = _service()
    state = _state_for_stitch()

    # After STITCH_BOTH, stitched=[prev, primary, next]; next iter has no neighbors
    mock_objects = _patch_chunk_objects({4: prev_chunk, 6: next_chunk, 3: None, 7: None})

    with patch("runtime.retrieval.ContentChunk.objects", mock_objects):
        with patch.object(service, "_stitch_decision", return_value="STITCH_BOTH"):
            stitched, decision, calls = service._apply_stitch_with_validator(
                state=state, primary_chunk=primary
            )

    assert len(stitched) == 3
    assert prev_chunk in stitched
    assert next_chunk in stitched
    assert primary in stitched
    assert calls == 1


def test_step9_stitch_max_5_chunk_guard() -> None:
    """9.5A guard: stitch stops at 5 chunks regardless of validator decision."""
    source_id = uuid.uuid4()
    primary = _chunk_ns(5, source_id)
    service = _service()
    state = _state_for_stitch()

    # Provide chunks at indices 6, 7, 8, 9 to allow 4 STITCH_NEXT rounds
    chunk_map = {
        4: None,
        6: _chunk_ns(6, source_id),
        7: _chunk_ns(7, source_id),
        8: _chunk_ns(8, source_id),
        9: _chunk_ns(9, source_id),
    }
    mock_objects = _patch_chunk_objects(chunk_map)

    with patch("runtime.retrieval.ContentChunk.objects", mock_objects):
        with patch.object(service, "_stitch_decision", return_value="STITCH_NEXT"):
            stitched, _decision, calls = service._apply_stitch_with_validator(
                state=state, primary_chunk=primary
            )

    assert len(stitched) == 5
    assert calls == 4  # 4 STITCH_NEXT decisions before while-guard fires


# ══════════════════════════════════════════════════════════════════
#  STEP 10 — 10.7.1: LISTEN fallback defaults
# ══════════════════════════════════════════════════════════════════


def _listen_state(*, style_signals=None, user_state_signals=None) -> RuntimeState:
    return RuntimeState(
        request_payload=SimpleNamespace(message="hello"),
        identity=SimpleNamespace(owner_kwargs=lambda: {}),
        quota_window=SimpleNamespace(),
        response_method=ResponseMethod.LISTEN,
        runtime_bundle={
            "current_message": "hello",
            "recent_turns": [],
            "context_summary": "",
            "long_term_memory": [],
        },
        normalized_reasoning_result={
            "intent": "emotional_support",
            "case_slots": {},
            "required_next_slots": [],
            "turn_strategy": {},
            "style_signals_next": style_signals or [],
            "user_state_signals_next": user_state_signals or [],
        },
    )


def test_step10_listen_empty_style_signals_defaults_to_neutral_gentle_brief() -> None:
    """10.7.1: LISTEN with no style_signals → default ['neutral_gentle_brief'] in payload."""
    state = _listen_state(style_signals=[])

    result = PromptAssemblyService().build(state=state)

    assert "Style signals: neutral_gentle_brief" in result.prompt_messages[1]["content"]


def test_step10_listen_empty_user_state_signals_defaults_to_neutral() -> None:
    """10.7.1: LISTEN with no user_state_signals → default ['neutral'] in payload."""
    state = _listen_state(user_state_signals=[])

    result = PromptAssemblyService().build(state=state)

    assert "User state signals: neutral" in result.prompt_messages[1]["content"]


# ══════════════════════════════════════════════════════════════════
#  STEP 10 — 10.7.2: REFLECT fallback omits missing optional fields
# ══════════════════════════════════════════════════════════════════


def _reflect_state(*, context_summary="", case_slots=None, intent="") -> RuntimeState:
    return RuntimeState(
        request_payload=SimpleNamespace(message="hello"),
        identity=SimpleNamespace(owner_kwargs=lambda: {}),
        quota_window=SimpleNamespace(),
        response_method=ResponseMethod.REFLECT,
        runtime_bundle={
            "current_message": "hello",
            "recent_turns": [],
            "context_summary": context_summary,
            "long_term_memory": [],
        },
        normalized_reasoning_result={
            "intent": intent,
            "case_slots": case_slots or {},
            "required_next_slots": [],
            "turn_strategy": {},
            "style_signals_next": ["none"],
            "user_state_signals_next": ["none"],
        },
    )


def test_step10_reflect_no_context_summary_omits_from_used_fields() -> None:
    """10.7.2: REFLECT with empty context_summary still builds valid prompt."""
    state = _reflect_state(context_summary="")

    result = PromptAssemblyService().build(state=state)

    assert result.prompt_debug_meta["builder_name"] == "build_reflect_prompt"


def test_step10_reflect_with_context_summary_includes_in_used_fields() -> None:
    """10.7.2: REFLECT with context_summary includes section in user content."""
    state = _reflect_state(context_summary="some context")

    result = PromptAssemblyService().build(state=state)

    assert "Context summary: some context" in result.prompt_messages[1]["content"]


def test_step10_reflect_no_intent_omits_from_used_fields() -> None:
    """10.7.2: REFLECT with no intent skips intent line, builder still runs."""
    state = _reflect_state(intent="")

    result = PromptAssemblyService().build(state=state)

    assert "- Intent:" not in result.prompt_messages[1]["content"]
    assert result.prompt_debug_meta["builder_name"] == "build_reflect_prompt"


def test_step10_reflect_with_intent_includes_in_used_fields() -> None:
    """10.7.2: REFLECT with intent present includes intent line."""
    state = _reflect_state(intent="self_understanding")

    result = PromptAssemblyService().build(state=state)

    assert "- Intent: self_understanding" in result.prompt_messages[1]["content"]


# ══════════════════════════════════════════════════════════════════
#  STEP 10 — 10.7.3: FOLLOWUP fallback tiers
# ══════════════════════════════════════════════════════════════════


def _followup_state(*, turn_strategy=None, context_summary="", recent_turns=None) -> RuntimeState:
    return RuntimeState(
        request_payload=SimpleNamespace(message="hello"),
        identity=SimpleNamespace(owner_kwargs=lambda: {}),
        quota_window=SimpleNamespace(),
        response_method=ResponseMethod.FOLLOWUP,
        runtime_bundle={
            "current_message": "hello",
            "recent_turns": recent_turns or [],
            "context_summary": context_summary,
            "long_term_memory": [],
        },
        normalized_reasoning_result={
            "intent": "continue_previous_topic",
            "case_slots": {"core_problem": "stress"},
            "required_next_slots": [],
            "turn_strategy": turn_strategy,
            "style_signals_next": ["none"],
            "user_state_signals_next": ["none"],
        },
    )


def test_step10_followup_tier1_with_strategy_and_summary() -> None:
    """10.7.3 tier 1: has turn_strategy + context_summary → both appear in user content."""
    state = _followup_state(
        turn_strategy={"focus": "continuity", "angle": "gentle", "avoid": []},
        context_summary="prior context",
    )

    result = PromptAssemblyService().build(state=state)
    content = result.prompt_messages[1]["content"]
    assert "Context summary: prior context" in content
    assert "Turn strategy: focus=continuity; angle=gentle" in content


def test_step10_followup_tier2_no_strategy_has_summary() -> None:
    """10.7.3 tier 2: no turn_strategy but has context_summary → summary appears, strategy absent."""
    state = _followup_state(turn_strategy=None, context_summary="prior context")

    result = PromptAssemblyService().build(state=state)
    content = result.prompt_messages[1]["content"]
    assert "Context summary: prior context" in content
    assert "Turn strategy:" not in content


def test_step10_followup_tier3_neither_strategy_nor_summary() -> None:
    """10.7.3 tier 3: no turn_strategy, no context_summary → both absent from rendered content."""
    state = _followup_state(turn_strategy=None, context_summary="")

    result = PromptAssemblyService().build(state=state)
    content = result.prompt_messages[1]["content"]
    assert "Turn strategy:" not in content
    assert "Context summary:" not in content
    assert result.prompt_debug_meta["builder_name"] == "build_followup_prompt"


# ══════════════════════════════════════════════════════════════════
#  STEP 12 — 12.4: quota_exhausted_after_turn when quota is exhausted
# ══════════════════════════════════════════════════════════════════

pytestmark_db = pytest.mark.django_db


class DummyGateway12:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses

    def complete(self, *, operation_key, turn, prompt_messages):
        _ = turn, prompt_messages
        key = operation_key.value if hasattr(operation_key, "value") else str(operation_key)
        return SimpleNamespace(text=self.responses[key])


@pytest.mark.django_db
def test_step12_quota_exhausted_after_turn_true() -> None:
    """12.4: when quota window is_exhausted=True → quota_exhausted_after_turn persisted as True."""
    from chat.services import IdentityContext

    guest = GuestIdentity.objects.create()
    identity = IdentityContext(guest_identity=guest)
    case = Case.objects.create(guest_identity=guest, topic="conflict", context_summary="old")
    chat = Chat.objects.create(guest_identity=guest, case=case)
    turn = ChatTurn.objects.create(
        guest_identity=guest,
        chat=chat,
        case=case,
        user_message_text="msg",
        assistant_response_text="resp",
        response_method=ResponseMethod.LISTEN.value,
        status="completed",
    )
    quota_window = UsageQuotaWindow.objects.create(
        guest_identity=guest,
        token_limit=10,
        used_tokens=10,  # already at limit
        is_exhausted=True,
    )

    state = SimpleNamespace(
        identity=identity,
        case=case,
        chat=chat,
        turn=turn,
        quota_window=quota_window,
        response_text="resp",
        runtime_bundle={"context_summary": "old", "long_term_memory": []},
        normalized_reasoning_result={
            "intent": "emotional_support",
            "case_slots": {},
            "explicit_profile_facts_next": [],
            "style_signals_next": [],
            "user_state_signals_next": [],
        },
    )

    gateway = DummyGateway12(
        responses={
            OperationKey.CONTEXT_SUMMARY_UPDATER.value: json.dumps({"has_meaningful_update": False}),
            OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value: json.dumps({"action": "no_update"}),
        }
    )

    PostTurnFinalizationService(
        llm_gateway=gateway,
        quota_service=QuotaService(),
        state_store=IdentityStateStoreService(),
    ).run(state=state)

    turn.refresh_from_db()
    assert turn.quota_exhausted_after_turn is True
