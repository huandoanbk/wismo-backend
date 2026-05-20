"""Unit tests for pingllm management command helpers."""

from __future__ import annotations

import pytest
from django.core.management.base import CommandError

from llm_ops.management.commands.pingllm import _build_probe_target, _default_api_suffix
from llm_ops.models import LLMGatewayConfig
from wismo.contracts.enums import LLMGatewayIntegrationKind, LLMGatewayMode


def _gateway(*, integration_kind: str, endpoint_url: str) -> LLMGatewayConfig:
    """Create an in-memory gateway config object for helper tests."""

    return LLMGatewayConfig(
        display_name="Gateway",
        integration_kind=integration_kind,
        endpoint_url=endpoint_url,
        api_key_ref="KEY",
        model_name="model",
        mode=LLMGatewayMode.CONVERSATION.value,
        params={},
        is_active=True,
    )


def test_build_probe_target_uses_base_endpoint_by_default() -> None:
    """Default probe should target endpoint URL root."""

    gateway = _gateway(
        integration_kind=LLMGatewayIntegrationKind.OPENAI_COMPATIBLE.value,
        endpoint_url="https://api.example.com/v1/",
    )

    target = _build_probe_target(gateway, api_probe=False)
    assert target.url == "https://api.example.com/v1"
    assert target.host == "api.example.com"
    assert target.port == 443
    assert target.scheme == "https"


@pytest.mark.parametrize(
    ("kind", "suffix"),
    [
        (LLMGatewayIntegrationKind.OPENAI_COMPATIBLE.value, "/chat/completions"),
        (LLMGatewayIntegrationKind.OPENAI_NATIVE.value, "/chat/completions"),
        (LLMGatewayIntegrationKind.AZURE_OPENAI_V1.value, "/chat/completions"),
        (LLMGatewayIntegrationKind.ANTHROPIC_NATIVE.value, "/messages"),
        (LLMGatewayIntegrationKind.OPENAI_EMBEDDINGS_V1.value, "/embeddings"),
        (LLMGatewayIntegrationKind.DEEPINFRA_RERANKER_V1.value, ""),
    ],
)
def test_default_api_suffix_by_integration(kind: str, suffix: str) -> None:
    """Each integration kind must map to canonical probe path."""

    assert _default_api_suffix(kind) == suffix


def test_build_probe_target_appends_api_suffix_when_enabled() -> None:
    """API probe mode should append integration-specific suffix."""

    gateway = _gateway(
        integration_kind=LLMGatewayIntegrationKind.ANTHROPIC_NATIVE.value,
        endpoint_url="https://api.anthropic.com/v1",
    )
    target = _build_probe_target(gateway, api_probe=True)
    assert target.url == "https://api.anthropic.com/v1/messages"


def test_build_probe_target_rejects_invalid_scheme() -> None:
    """Invalid endpoint schemes must fail with a clear error."""

    gateway = _gateway(
        integration_kind=LLMGatewayIntegrationKind.OPENAI_COMPATIBLE.value,
        endpoint_url="ftp://example.com/v1",
    )
    with pytest.raises(CommandError):
        _build_probe_target(gateway, api_probe=False)
