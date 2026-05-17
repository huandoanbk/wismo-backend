"""Tests for runtime config default registry and validation helpers."""

from __future__ import annotations

import pytest

from admin_config.defaults import (
    ensure_runtime_config_defaults,
    runtime_config_default_specs,
    validate_runtime_config_value,
)
from admin_config.models import RuntimeConfig
from runtime.services import RuntimeConfigService

pytestmark = pytest.mark.django_db


def test_ensure_runtime_config_defaults_creates_all_missing_keys() -> None:
    """Default sync should create one RuntimeConfig row per canonical key."""

    RuntimeConfig.objects.all().delete()
    result = ensure_runtime_config_defaults()

    assert result.created_count == len(runtime_config_default_specs())
    keys = set(RuntimeConfig.objects.values_list("key", flat=True))
    assert keys == {spec.key for spec in runtime_config_default_specs()}


def test_validate_runtime_config_value_normalizes_known_key() -> None:
    """Known runtime config schema should coerce positive integer fields."""

    normalized = validate_runtime_config_value(
        key=RuntimeConfigService.INPUT_LIMITS_KEY,
        value={"max_message_length_chars": "9000", "max_payload_bytes": 77777},
    )

    assert normalized == {"max_message_length_chars": 9000, "max_payload_bytes": 77777}


def test_validate_runtime_config_value_rejects_unknown_fields_for_known_key() -> None:
    """Known config keys should fail when unknown payload fields are provided."""

    with pytest.raises(ValueError, match="Unexpected keys"):
        validate_runtime_config_value(
            key=RuntimeConfigService.INPUT_LIMITS_KEY,
            value={
                "max_message_length_chars": 9000,
                "max_payload_bytes": 77777,
                "extra": 1,
            },
        )


def test_validate_runtime_config_value_accepts_step_trace_level_enum() -> None:
    """Step trace config must accept only canonical level enum values."""

    normalized = validate_runtime_config_value(
        key=RuntimeConfigService.STEP_TRACE_KEY,
        value={"level": "FULL"},
    )
    assert normalized == {"level": "full"}

    with pytest.raises(ValueError, match="must be one of: off, meta, full"):
        validate_runtime_config_value(
            key=RuntimeConfigService.STEP_TRACE_KEY,
            value={"level": "verbose"},
        )
