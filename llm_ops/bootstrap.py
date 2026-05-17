"""Bootstrap helpers for deterministic LLM gateway configuration."""

from __future__ import annotations

from dataclasses import dataclass

from llm_ops.models import LLMGatewayConfig, LLMOperation
from wismo.contracts.enums import LLMGatewayIntegrationKind, LLMGatewayMode, OperationKey

CANONICAL_GATEWAY_NAME = "Local Stub Gateway"
CANONICAL_GATEWAY_INTEGRATION_KIND = LLMGatewayIntegrationKind.OPENAI_COMPATIBLE.value
CANONICAL_GATEWAY_ENDPOINT_URL = "http://local_stub.invalid"
CANONICAL_GATEWAY_API_KEY_REF = "LOCAL_STUB_API_KEY"
CANONICAL_GATEWAY_MODEL_NAME = "foundation-stub"
CANONICAL_GATEWAY_MODE = LLMGatewayMode.CONVERSATION.value
CANONICAL_GATEWAY_PARAMS = {
    "adapter": "local_stub",
    "allow_stub": True,
    "temperature": 0.0,
    "max_output_tokens": 256,
}


@dataclass(frozen=True)
class LLMGatewayBootstrapCounts:
    """Counters describing the bootstrap result."""

    gateways_created: int
    operations_created: int
    operations_bound: int
    operations_activated: int


def bootstrap_default_llm_gateway_config() -> LLMGatewayBootstrapCounts:
    """Seed a deterministic local gateway config for dev and tests."""

    gateway, gateway_created = LLMGatewayConfig.objects.get_or_create(
        display_name=CANONICAL_GATEWAY_NAME,
        defaults={
            "integration_kind": CANONICAL_GATEWAY_INTEGRATION_KIND,
            "endpoint_url": CANONICAL_GATEWAY_ENDPOINT_URL,
            "api_key_ref": CANONICAL_GATEWAY_API_KEY_REF,
            "model_name": CANONICAL_GATEWAY_MODEL_NAME,
            "mode": CANONICAL_GATEWAY_MODE,
            "params": CANONICAL_GATEWAY_PARAMS,
            "is_active": True,
        },
    )
    if not gateway_created:
        update_fields: list[str] = []
        if gateway.integration_kind != CANONICAL_GATEWAY_INTEGRATION_KIND:
            gateway.integration_kind = CANONICAL_GATEWAY_INTEGRATION_KIND
            update_fields.append("integration_kind")
        if gateway.endpoint_url != CANONICAL_GATEWAY_ENDPOINT_URL:
            gateway.endpoint_url = CANONICAL_GATEWAY_ENDPOINT_URL
            update_fields.append("endpoint_url")
        if gateway.api_key_ref != CANONICAL_GATEWAY_API_KEY_REF:
            gateway.api_key_ref = CANONICAL_GATEWAY_API_KEY_REF
            update_fields.append("api_key_ref")
        if gateway.model_name != CANONICAL_GATEWAY_MODEL_NAME:
            gateway.model_name = CANONICAL_GATEWAY_MODEL_NAME
            update_fields.append("model_name")
        if gateway.mode != CANONICAL_GATEWAY_MODE:
            gateway.mode = CANONICAL_GATEWAY_MODE
            update_fields.append("mode")
        if gateway.params != CANONICAL_GATEWAY_PARAMS:
            gateway.params = CANONICAL_GATEWAY_PARAMS
            update_fields.append("params")
        if not gateway.is_active:
            gateway.is_active = True
            update_fields.append("is_active")
        if update_fields:
            update_fields.append("updated_at")
            gateway.save(update_fields=update_fields)

    operations_created = 0
    operations_bound = 0
    operations_activated = 0
    for operation_key in OperationKey:
        operation, created = LLMOperation.objects.get_or_create(
            code=operation_key.value,
            defaults={
                "description": operation_key.name.replace("_", " ").title(),
                "gateway": gateway,
                "is_active": True,
            },
        )
        if created:
            operations_created += 1
            operations_bound += 1
            continue

        update_fields: list[str] = []
        if operation.description != operation_key.name.replace("_", " ").title():
            operation.description = operation_key.name.replace("_", " ").title()
            update_fields.append("description")
        if operation.gateway_id != gateway.id:
            operation.gateway = gateway
            update_fields.append("gateway")
            operations_bound += 1
        if not operation.is_active:
            operation.is_active = True
            update_fields.append("is_active")
            operations_activated += 1
        if update_fields:
            update_fields.append("updated_at")
            operation.save(update_fields=update_fields)

    return LLMGatewayBootstrapCounts(
        gateways_created=1 if gateway_created else 0,
        operations_created=operations_created,
        operations_bound=operations_bound,
        operations_activated=operations_activated,
    )
