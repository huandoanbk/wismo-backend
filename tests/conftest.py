"""Shared pytest configuration for Django-backed tests."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wismo.settings_dev")


@pytest.fixture(autouse=True)
def seed_llm_gateway_config(db) -> None:
    """Seed canonical LLM gateway config for database-backed tests."""

    from llm_ops.bootstrap import bootstrap_default_llm_gateway_config

    bootstrap_default_llm_gateway_config()
