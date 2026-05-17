"""Unit tests for Main Flow Step 6 runtime bundle loading."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from accounts.models import GuestIdentity
from chat.models import Case, Chat, ChatTurn
from chat.services import IdentityContext
from memory.models import MemoryItem, UserPreferenceState, UserProfileState, UserStateSnapshot
from runtime.orchestrator import RuntimeOrchestrator, RuntimeState
from runtime.services import RuntimeBundleService
from wismo.contracts.enums import ResponseMethod, TurnStatus

pytestmark = pytest.mark.django_db


def _create_chat_state(*, with_case: bool) -> tuple[IdentityContext, Chat, ChatTurn, Case | None]:
    guest = GuestIdentity.objects.create()
    identity = IdentityContext(guest_identity=guest)
    case = None
    if with_case:
        case = Case.objects.create(
            guest_identity=guest,
            topic="topic",
            context_summary="case summary",
        )
    chat = Chat.objects.create(guest_identity=guest, case=case, opening_input_text="open")
    ChatTurn.objects.create(
        guest_identity=guest,
        chat=chat,
        case=case,
        user_message_text="old-1",
        assistant_response_text="a1",
        response_method=ResponseMethod.ASK.value,
        status=TurnStatus.COMPLETED.value,
    )
    ChatTurn.objects.create(
        guest_identity=guest,
        chat=chat,
        case=case,
        user_message_text="old-2",
        assistant_response_text="a2",
        response_method=ResponseMethod.LISTEN.value,
        status=TurnStatus.COMPLETED.value,
    )
    current = ChatTurn.objects.create(
        guest_identity=guest,
        chat=chat,
        case=case,
        user_message_text="current",
        status="processing",
    )
    return identity, chat, current, case


def test_runtime_bundle_resolved_case_loads_context_and_active_memory() -> None:
    identity, chat, current, case = _create_chat_state(with_case=True)
    assert case is not None
    MemoryItem.objects.create(
        guest_identity=identity.guest_identity,
        case=case,
        memory_type="theme",
        normalized_text="keep this",
        confidence=0.8,
        evidence_count=2,
        is_active=True,
    )
    MemoryItem.objects.create(
        guest_identity=identity.guest_identity,
        case=case,
        memory_type="theme",
        normalized_text="drop this",
        confidence=0.7,
        evidence_count=1,
        is_active=False,
    )

    bundle = RuntimeBundleService().build_bundle(
        chat=chat,
        turn=current,
        case=case,
        identity=identity,
        current_message="hello",
    )

    assert bundle["current_message"] == "hello"
    assert [item["user_message_text"] for item in bundle["recent_turns"]] == ["old-1", "old-2"]
    assert bundle["context_summary"] == "case summary"
    assert bundle["user_profile"] == {}
    assert bundle["user_preference"] == {}
    assert bundle["user_state"] == {}
    assert len(bundle["long_term_memory"]) == 1
    assert bundle["long_term_memory"][0]["text"] == "keep this"


def test_runtime_bundle_null_case_keeps_case_level_fields_empty() -> None:
    identity, chat, current, case = _create_chat_state(with_case=False)
    assert case is None

    bundle = RuntimeBundleService().build_bundle(
        chat=chat,
        turn=current,
        case=None,
        identity=identity,
        current_message="hello",
    )

    assert bundle["context_summary"] == ""
    assert bundle["long_term_memory"] == []


def test_runtime_bundle_memory_failure_falls_back_to_empty_list() -> None:
    identity, chat, current, case = _create_chat_state(with_case=True)
    assert case is not None

    with patch("runtime.services.MemoryItem.objects.filter", side_effect=RuntimeError("boom")):
        bundle = RuntimeBundleService().build_bundle(
            chat=chat,
            turn=current,
            case=case,
            identity=identity,
            current_message="hello",
        )

    assert bundle["long_term_memory"] == []


def test_runtime_bundle_recent_turns_excludes_non_completed_turns() -> None:
    identity, chat, current, case = _create_chat_state(with_case=True)
    assert case is not None
    ChatTurn.objects.create(
        guest_identity=identity.guest_identity,
        chat=chat,
        case=case,
        user_message_text="failed-old",
        assistant_response_text="bad",
        response_method=ResponseMethod.ASK.value,
        status=TurnStatus.FAILED.value,
    )

    bundle = RuntimeBundleService().build_bundle(
        chat=chat,
        turn=current,
        case=case,
        identity=identity,
        current_message="hello",
    )

    assert [item["user_message_text"] for item in bundle["recent_turns"]] == ["old-1", "old-2"]


def test_runtime_bundle_loads_persisted_identity_state() -> None:
    identity, chat, current, case = _create_chat_state(with_case=True)
    assert case is not None
    UserProfileState.objects.create(
        guest_identity=identity.guest_identity,
        profile_data={"facts": ["works remotely"]},
        version=2,
    )
    UserPreferenceState.objects.create(
        guest_identity=identity.guest_identity,
        preference_data={"prefers_brief_response": True},
        evidence_counts={"prefers_brief_response": 3},
    )
    UserStateSnapshot.objects.create(
        guest_identity=identity.guest_identity,
        primary_state="overwhelmed",
        secondary_state="ruminating",
        raw_signals=["overwhelmed", "ruminating"],
    )

    bundle = RuntimeBundleService().build_bundle(
        chat=chat,
        turn=current,
        case=case,
        identity=identity,
        current_message="hello",
    )

    assert bundle["user_profile"] == {"facts": ["works remotely"]}
    assert bundle["user_preference"] == {"prefers_brief_response": True}
    assert bundle["user_state"]["primary_state"] == "overwhelmed"


def test_orchestrator_step6_assembles_bundle_once_and_downstream_reuses_it() -> None:
    identity, chat, current, case = _create_chat_state(with_case=True)
    state = RuntimeState(
        request_payload=SimpleNamespace(message="hello"),
        identity=identity,
        quota_window=SimpleNamespace(),
        chat=chat,
        case=case,
        turn=current,
    )
    orchestrator = RuntimeOrchestrator()

    calls: list[dict] = []

    def _fake_build_bundle(**kwargs):
        calls.append(kwargs)
        return {
            "current_message": "hello",
            "recent_turns": [{"user_message_text": "x"}],
            "context_summary": "sum",
            "user_profile": {},
            "user_preference": {},
            "user_state": {},
            "long_term_memory": [],
        }

    orchestrator.bundle_service.build_bundle = _fake_build_bundle  # type: ignore[assignment]

    orchestrator._load_runtime_bundle(state)
    snapshot = dict(state.runtime_bundle)
    orchestrator._full_reasoning(state)
    orchestrator._validate_and_select_response_method(state)
    orchestrator._knowledge_retrieval(state)

    assert len(calls) == 1
    assert state.runtime_bundle["current_message"] == snapshot["current_message"]
    assert state.runtime_bundle["recent_turns"] == snapshot["recent_turns"]
    assert state.runtime_bundle["context_summary"] == snapshot["context_summary"]
    assert state.runtime_bundle["user_profile"] == snapshot["user_profile"]
    assert state.runtime_bundle["user_preference"] == snapshot["user_preference"]
    assert state.runtime_bundle["user_state"] == snapshot["user_state"]
    assert state.runtime_bundle["long_term_memory"] == snapshot["long_term_memory"]
