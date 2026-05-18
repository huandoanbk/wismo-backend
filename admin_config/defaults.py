"""Runtime config defaults and validation helpers for Django admin."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from admin_config.models import RuntimeConfig
from runtime.services import RuntimeConfigService


@dataclass(frozen=True)
class RuntimeConfigDefaultSpec:
    """Canonical default for one runtime config key."""

    key: str
    description: str
    default_value: dict[str, Any]
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeConfigSyncResult:
    """Counters for default runtime config synchronization."""

    created_count: int
    updated_description_count: int
    activated_count: int


_DEFAULT_SPECS: tuple[RuntimeConfigDefaultSpec, ...] = (
    RuntimeConfigDefaultSpec(
        key=RuntimeConfigService.INPUT_LIMITS_KEY,
        description="Request gate input limits (message length and payload bytes).",
        default_value={
            "max_message_length_chars": RuntimeConfigService.DEFAULT_INPUT_LIMITS.max_message_length_chars,
            "max_payload_bytes": RuntimeConfigService.DEFAULT_INPUT_LIMITS.max_payload_bytes,
        },
        required_fields=("max_message_length_chars", "max_payload_bytes"),
    ),
    RuntimeConfigDefaultSpec(
        key=RuntimeConfigService.GUEST_QUOTA_POLICY_KEY,
        description="Quota window policy for guest identities.",
        default_value={
            "token_limit": RuntimeConfigService.DEFAULT_GUEST_QUOTA_POLICY.token_limit,
            "window_seconds": RuntimeConfigService.DEFAULT_GUEST_QUOTA_POLICY.window_seconds,
        },
        required_fields=("token_limit", "window_seconds"),
    ),
    RuntimeConfigDefaultSpec(
        key=RuntimeConfigService.USER_QUOTA_POLICY_KEY,
        description="Quota window policy for registered users.",
        default_value={
            "token_limit": RuntimeConfigService.DEFAULT_USER_QUOTA_POLICY.token_limit,
            "window_seconds": RuntimeConfigService.DEFAULT_USER_QUOTA_POLICY.window_seconds,
        },
        required_fields=("token_limit", "window_seconds"),
    ),
    RuntimeConfigDefaultSpec(
        key=RuntimeConfigService.PENDING_INPUT_LIMITS_KEY,
        description="Bounds for pending_input_text accumulation while quota is exhausted.",
        default_value={
            "max_appends": RuntimeConfigService.DEFAULT_PENDING_INPUT_LIMITS.max_appends,
            "max_chars": RuntimeConfigService.DEFAULT_PENDING_INPUT_LIMITS.max_chars,
        },
        required_fields=("max_appends", "max_chars"),
    ),
    RuntimeConfigDefaultSpec(
        key=RuntimeConfigService.STEP_TRACE_KEY,
        description="Runtime step-trace capture level for ChatTurn admin observability: off | meta | full.",
        default_value={
            "level": RuntimeConfigService.DEFAULT_STEP_TRACE.level,
        },
        required_fields=("level",),
    ),
    RuntimeConfigDefaultSpec(
        key=RuntimeConfigService.GUEST_SESSION_KEY,
        description="Guest session idle TTL in hours. Session expires if no activity within this window.",
        default_value={
            "idle_ttl_hours": RuntimeConfigService.DEFAULT_GUEST_SESSION_POLICY.idle_ttl_hours,
        },
        required_fields=("idle_ttl_hours",),
    ),
    RuntimeConfigDefaultSpec(
        key=RuntimeConfigService.ADMIN_CONTACT_KEY,
        description="Destination email address for contact form submissions.",
        default_value={
            "email": RuntimeConfigService.DEFAULT_ADMIN_CONTACT_POLICY.email,
        },
        required_fields=("email",),
    ),
    RuntimeConfigDefaultSpec(
        key=RuntimeConfigService.PROMPT_ASSEMBLY_KEY,
        description="Prompt assembly compaction threshold in estimated tokens. Compact triggers when prompt exceeds this limit.",
        default_value={
            "max_estimated_tokens": RuntimeConfigService.DEFAULT_PROMPT_ASSEMBLY_POLICY.max_estimated_tokens,
        },
        required_fields=("max_estimated_tokens",),
    ),
)


def runtime_config_default_specs() -> tuple[RuntimeConfigDefaultSpec, ...]:
    """Return the canonical runtime config default specifications."""

    return _DEFAULT_SPECS


def runtime_config_default_spec_map() -> dict[str, RuntimeConfigDefaultSpec]:
    """Return a mapping from config key to default specification."""

    return {spec.key: spec for spec in _DEFAULT_SPECS}


def ensure_runtime_config_defaults(*, activate_existing: bool = False) -> RuntimeConfigSyncResult:
    """Create missing default runtime config records and patch empty descriptions."""

    created_count = 0
    updated_description_count = 0
    activated_count = 0

    with transaction.atomic():
        for spec in _DEFAULT_SPECS:
            record = RuntimeConfig.objects.filter(key=spec.key).order_by("-updated_at", "-created_at").first()
            if record is None:
                RuntimeConfig.objects.create(
                    key=spec.key,
                    value=copy.deepcopy(spec.default_value),
                    description=spec.description,
                    is_active=True,
                )
                created_count += 1
                continue

            update_fields: list[str] = []
            if not record.description.strip():
                record.description = spec.description
                update_fields.append("description")
                updated_description_count += 1
            if activate_existing and not record.is_active:
                record.is_active = True
                update_fields.append("is_active")
                activated_count += 1
            if update_fields:
                update_fields.append("updated_at")
                record.save(update_fields=update_fields)

    return RuntimeConfigSyncResult(
        created_count=created_count,
        updated_description_count=updated_description_count,
        activated_count=activated_count,
    )


def validate_runtime_config_value(*, key: str, value: Any) -> dict[str, Any]:
    """Validate and normalize a runtime config value payload for one key."""

    if not isinstance(value, dict):
        raise ValueError("Value must be a JSON object (mapping).")

    spec = runtime_config_default_spec_map().get(key)
    if spec is None:
        return value

    if key == RuntimeConfigService.ADMIN_CONTACT_KEY:
        raw_email = value.get("email", "")
        if not isinstance(raw_email, str):
            raise ValueError("'email' must be a string.")
        extra_keys = sorted(set(value.keys()) - {"email"})
        if extra_keys:
            raise ValueError(f"Unexpected keys for '{key}': {', '.join(extra_keys)}")
        return {"email": raw_email.strip()}

    if key == RuntimeConfigService.GUEST_SESSION_KEY:
        raw_hours = value.get("idle_ttl_hours", spec.default_value["idle_ttl_hours"])
        try:
            hours = int(raw_hours)
        except (TypeError, ValueError) as exc:
            raise ValueError("'idle_ttl_hours' must be a positive integer.") from exc
        if hours <= 0:
            raise ValueError("'idle_ttl_hours' must be a positive integer.")
        extra_keys = sorted(set(value.keys()) - {"idle_ttl_hours"})
        if extra_keys:
            raise ValueError(f"Unexpected keys for '{key}': {', '.join(extra_keys)}")
        return {"idle_ttl_hours": hours}

    if key == RuntimeConfigService.STEP_TRACE_KEY:
        raw_level = value.get("level", spec.default_value["level"])
        if not isinstance(raw_level, str):
            raise ValueError("'level' must be one of: off, meta, full.")
        level = raw_level.strip().lower()
        if level not in {"off", "meta", "full"}:
            raise ValueError("'level' must be one of: off, meta, full.")
        extra_keys = sorted(set(value.keys()) - {"level"})
        if extra_keys:
            extras = ", ".join(extra_keys)
            raise ValueError(f"Unexpected keys for '{key}': {extras}")
        return {"level": level}

    normalized: dict[str, Any] = {}
    for field_name in spec.required_fields:
        raw = value.get(field_name, spec.default_value[field_name])
        try:
            parsed = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"'{field_name}' must be a positive integer.") from exc
        if parsed <= 0:
            raise ValueError(f"'{field_name}' must be a positive integer.")
        normalized[field_name] = parsed

    extra_keys = sorted(set(value.keys()) - set(spec.required_fields))
    if extra_keys:
        extras = ", ".join(extra_keys)
        raise ValueError(f"Unexpected keys for '{key}': {extras}")
    return normalized
