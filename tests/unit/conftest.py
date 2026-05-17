"""Pytest fixtures scoped to database-backed unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def seed_llm_gateway_config(db) -> None:
    """Seed canonical LLM gateway config for unit tests requiring the DB."""

    from llm_ops.bootstrap import bootstrap_default_llm_gateway_config

    bootstrap_default_llm_gateway_config()
