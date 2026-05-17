"""Orchestrator skeleton tests."""

import inspect

from runtime.orchestrator import RuntimeOrchestrator


def test_orchestrator_stream_lists_mvp_steps_in_order() -> None:
    """The SSE generator keeps the MVP step ordering visible."""

    source = inspect.getsource(RuntimeOrchestrator.stream)
    expected_order = [
        "_resolve_chat_context",
        "_create_turn",
        "_fast_triage",
        "_handle_control_branch_if_needed",
        "_resolve_case",
        "_load_runtime_bundle",
        "_full_reasoning",
        "_validate_and_select_response_method",
        "_knowledge_retrieval",
        "_prompt_assembly",
        "_response_generation_and_persist",
        "_post_turn_finalization",
    ]

    positions = [source.index(step) for step in expected_order]
    assert positions == sorted(positions)
