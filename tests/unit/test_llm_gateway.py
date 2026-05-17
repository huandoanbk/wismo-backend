"""Regression tests for the LLM gateway foundation."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.admin.sites import site
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from accounts.models import GuestIdentity
from accounts.services import GUEST_COOKIE_NAME
from chat.models import Chat, ChatTurn
from consents.services import ConsentService
from llm_ops.bootstrap import bootstrap_default_llm_gateway_config
from llm_ops.errors import (
    LLM_GATEWAY_CONFIG_INVALID,
    LLM_GATEWAY_CONFIG_MISSING,
    LLM_GATEWAY_PROVIDER_ERROR,
    LLM_GATEWAY_PROVIDER_UNAVAILABLE,
    LLMGatewayConfigurationError,
    LLMGatewayProviderError,
    LLMGatewayProviderUnavailableError,
)
from llm_ops.gateway import LLMGateway
from llm_ops.models import LLMGatewayConfig, LLMOperation, LLMUsageEvent
from llm_ops.providers import (
    AnthropicNativeLLMAdapter,
    OpenAICompatibleLLMAdapter,
    OpenAIEmbeddingsLLMAdapter,
)
from llm_ops.services import LLMUsageQueryService
from runtime.models import OperationalLog, UsageQuotaWindow
from runtime.orchestrator import RuntimeOrchestrator
from wismo.contracts.enums import (
    LLMGatewayIntegrationKind,
    LLMGatewayMode,
    LLMUsageStatus,
    OperationKey,
    Step12FinalizationStatus,
    TurnStatus,
    UsageAccountingStatus,
)

pytestmark = pytest.mark.django_db


class RaisingAdapter:
    """Adapter stub that simulates a provider failure."""

    def complete(self, *, gateway, operation, prompt_messages: list[dict]):  # noqa: D401
        """Raise a provider-side failure."""

        raise RuntimeError("upstream failed")


class ConfigurationMissingGateway:
    """Gateway stub that simulates a config failure."""

    def complete(self, *, operation_key: OperationKey, turn, prompt_messages: list[dict]):  # noqa: D401
        """Raise the canonical missing-config error."""

        raise LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_MISSING)


class CapturingTransport:
    """Transport stub that captures provider requests."""

    def __init__(self, response: dict[str, object], status_code: int = 200) -> None:
        self.response = response
        self.status_code = status_code
        self.requests: list[object] = []

    def send(self, request):  # noqa: D401
        """Record the request and return the configured response."""

        self.requests.append(request)
        from llm_ops.providers import LLMProviderResult

        return LLMProviderResult(status_code=self.status_code, json_body=self.response, text="")


def create_turn() -> ChatTurn:
    """Create a minimal guest-owned turn for gateway tests."""

    guest = GuestIdentity.objects.create()
    chat = Chat.objects.create(
        guest_identity=guest,
        chat_display_name="Test chat",
        opening_input_text="",
        last_activity_at=timezone.now(),
    )
    return ChatTurn.objects.create(
        chat=chat,
        guest_identity=guest,
        user_message_text="hello world",
    )


def make_guest_request(*, guest: GuestIdentity):
    """Return a request object resolved by the request gate."""

    request = APIRequestFactory().post("/api/chat/message/", {}, format="json")
    request.user = AnonymousUser()
    request.COOKIES[GUEST_COOKIE_NAME] = str(guest.id)
    return request


def test_bootstrap_helper_seeds_canonical_gateway_config() -> None:
    """Bootstrap helper creates one active gateway and bound operations."""

    LLMOperation.objects.all().delete()
    LLMGatewayConfig.objects.all().delete()

    result = bootstrap_default_llm_gateway_config()

    assert result.gateways_created == 1
    assert result.operations_created == len(OperationKey)
    assert result.operations_bound == len(OperationKey)
    assert set(LLMGateway().adapter_registry) == {
        "local_stub",
        LLMGatewayIntegrationKind.OPENAI_COMPATIBLE.value,
        LLMGatewayIntegrationKind.OPENAI_EMBEDDINGS_V1.value,
        LLMGatewayIntegrationKind.ANTHROPIC_NATIVE.value,
        LLMGatewayIntegrationKind.AZURE_OPENAI_V1.value,
        LLMGatewayIntegrationKind.OPENAI_NATIVE.value,
    }
    assert LLMUsageEvent.objects.count() == 0
    assert LLMGatewayConfig.objects.filter(display_name="Local Stub Gateway", is_active=True).exists()
    assert LLMOperation.objects.filter(is_active=True, gateway__display_name="Local Stub Gateway").count() == len(OperationKey)


def test_gateway_records_success_usage_event() -> None:
    """Gateway persists a usage event for a successful local completion."""

    turn = create_turn()
    completion = LLMGateway().complete(
        operation_key=OperationKey.RESPONSE_GENERATION,
        turn=turn,
        prompt_messages=[{"role": "user", "content": "hello"}],
    )

    usage_event = completion.usage_event

    assert completion.text
    assert usage_event.turn_id == turn.id
    assert usage_event.operation_key == OperationKey.RESPONSE_GENERATION.value
    assert usage_event.status == LLMUsageStatus.SUCCESS.value
    assert usage_event.error_code == ""
    assert usage_event.supplier_name == "Local Stub Gateway"
    assert usage_event.model_name == "foundation-stub"
    assert usage_event.total_billable_tokens == (
        usage_event.input_tokens
        + usage_event.cached_input_tokens
        + usage_event.output_tokens
        + usage_event.cache_write_tokens
    )
    assert turn.llm_usage_events.count() == 1
    quota_window = UsageQuotaWindow.current_for_identity(guest_identity=turn.guest_identity)
    assert quota_window.used_tokens == usage_event.total_billable_tokens


def test_gateway_missing_config_raises_canonical_error() -> None:
    """Gateway fails closed when a canonical operation is missing."""

    turn = create_turn()
    LLMOperation.objects.filter(code=OperationKey.RESPONSE_GENERATION.value).delete()

    with pytest.raises(LLMGatewayConfigurationError) as excinfo:
        LLMGateway().complete(
            operation_key=OperationKey.RESPONSE_GENERATION,
            turn=turn,
            prompt_messages=[{"role": "user", "content": "hello"}],
        )

    assert excinfo.value.code == LLM_GATEWAY_CONFIG_MISSING
    assert turn.llm_usage_events.count() == 0


def test_gateway_invalid_config_raises_canonical_error() -> None:
    """Gateway rejects inactive gateway configuration."""

    turn = create_turn()
    operation = LLMOperation.objects.select_related("gateway").get(code=OperationKey.RESPONSE_GENERATION.value)
    operation.gateway.is_active = False
    operation.gateway.save(update_fields=["is_active"])

    with pytest.raises(LLMGatewayConfigurationError) as excinfo:
        LLMGateway().complete(
            operation_key=OperationKey.RESPONSE_GENERATION,
            turn=turn,
            prompt_messages=[{"role": "user", "content": "hello"}],
        )

    assert excinfo.value.code == LLM_GATEWAY_CONFIG_INVALID
    assert turn.llm_usage_events.count() == 0


def test_unbound_operation_raises_canonical_error() -> None:
    """Gateway fails closed when a newly introduced operation has no gateway."""

    turn = create_turn()
    LLMOperation.objects.create(
        code="llm_triage_classifier_light",
        description="LLM triage classifier light",
        gateway=None,
        is_active=True,
    )

    with pytest.raises(LLMGatewayConfigurationError) as excinfo:
        LLMGateway().complete(
            operation_key="llm_triage_classifier_light",
            turn=turn,
            prompt_messages=[{"role": "user", "content": "hello"}],
        )

    assert excinfo.value.code == LLM_GATEWAY_CONFIG_INVALID
    assert turn.llm_usage_events.count() == 0


def test_gateway_provider_unavailable_persists_failure_usage_event() -> None:
    """Gateway logs a failed usage event when no adapter is available."""

    turn = create_turn()

    with pytest.raises(LLMGatewayProviderUnavailableError) as excinfo:
        LLMGateway(adapter_registry={}).complete(
            operation_key=OperationKey.RESPONSE_GENERATION,
            turn=turn,
            prompt_messages=[{"role": "user", "content": "hello"}],
        )

    usage_event = turn.llm_usage_events.get()
    assert excinfo.value.code == LLM_GATEWAY_PROVIDER_UNAVAILABLE
    assert usage_event.status == LLMUsageStatus.FAILED.value
    assert usage_event.error_code == LLM_GATEWAY_PROVIDER_UNAVAILABLE
    assert usage_event.operation_key == OperationKey.RESPONSE_GENERATION.value
    assert usage_event.total_billable_tokens == 0


def test_gateway_provider_error_persists_failure_usage_event() -> None:
    """Gateway logs a failed usage event when the provider adapter raises."""

    turn = create_turn()

    with pytest.raises(LLMGatewayProviderError) as excinfo:
        LLMGateway(adapter_registry={"local_stub": RaisingAdapter()}).complete(
            operation_key=OperationKey.RESPONSE_GENERATION,
            turn=turn,
            prompt_messages=[{"role": "user", "content": "hello"}],
        )

    usage_event = turn.llm_usage_events.get()
    assert excinfo.value.code == LLM_GATEWAY_PROVIDER_ERROR
    assert usage_event.status == LLMUsageStatus.FAILED.value
    assert usage_event.error_code == LLM_GATEWAY_PROVIDER_ERROR
    assert usage_event.total_billable_tokens == 0


def test_openai_style_adapter_serializes_conversation_payload() -> None:
    """OpenAI-compatible adapters keep conversation payloads structured."""

    transport = CapturingTransport(
        response={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }
    )
    adapter = OpenAICompatibleLLMAdapter(transport=transport)
    gateway = LLMGatewayConfig(
        display_name="DeepInfra-Deepseek v3.1",
        integration_kind=LLMGatewayIntegrationKind.OPENAI_COMPATIBLE.value,
        endpoint_url="https://api.deepinfra.com/v1/openai",
        api_key_ref="DEEPINFRA_API_KEY",
        model_name="deepseek-ai/DeepSeek-V3",
        mode=LLMGatewayMode.CONVERSATION.value,
        params={"temperature": 0.2, "max_output_tokens": 1024},
    )
    operation = LLMOperation(code="response_generation", description="Response generation", gateway=gateway)

    response = adapter.complete(
        gateway=gateway,
        operation=operation,
        prompt_messages=[
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hello"},
        ],
    )

    request = transport.requests[0]
    assert request.url.endswith("/chat/completions")
    assert request.json["model"] == "deepseek-ai/DeepSeek-V3"
    assert request.json["messages"] == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Hello"},
    ]
    assert request.json["max_tokens"] == 1024
    assert response.text == "ok"


def test_anthropic_adapter_hoists_system_prompt_in_single_message_mode() -> None:
    """Anthropic adapters hoist system/developer prompts and collapse the rest."""

    transport = CapturingTransport(
        response={
            "content": [{"type": "text", "text": "sure"}],
            "usage": {"input_tokens": 5, "output_tokens": 1},
        }
    )
    adapter = AnthropicNativeLLMAdapter(transport=transport)
    gateway = LLMGatewayConfig(
        display_name="Claude Gateway",
        integration_kind=LLMGatewayIntegrationKind.ANTHROPIC_NATIVE.value,
        endpoint_url="https://api.anthropic.com/v1",
        api_key_ref="ANTHROPIC_API_KEY",
        model_name="claude-sonnet-4-1",
        mode=LLMGatewayMode.SINGLE_MESSAGE.value,
        params={"max_output_tokens": 256},
    )
    operation = LLMOperation(code="triage_classifier", description="Triage classifier", gateway=gateway)

    response = adapter.complete(
        gateway=gateway,
        operation=operation,
        prompt_messages=[
            {"role": "system", "content": "You are precise."},
            {"role": "developer", "content": "Follow the policy."},
            {"role": "user", "content": "Hello"},
        ],
    )

    request = transport.requests[0]
    assert request.url.endswith("/messages")
    assert request.headers["x-api-key"] == "ANTHROPIC_API_KEY"
    assert request.json["system"] == "You are precise.\nFollow the policy."
    assert request.json["messages"] == [{"role": "user", "content": "USER: Hello"}]
    assert response.text == "sure"


def test_openai_embeddings_adapter_serializes_embeddings_payload() -> None:
    """OpenAI embeddings adapter must call /embeddings and normalize vector JSON."""

    transport = CapturingTransport(
        response={
            "data": [{"embedding": [0.1, 0.2, 0.3]}],
            "usage": {"prompt_tokens": 7, "total_tokens": 7},
        }
    )
    adapter = OpenAIEmbeddingsLLMAdapter(transport=transport)
    gateway = LLMGatewayConfig(
        display_name="DeepInfra BGE-M3",
        integration_kind=LLMGatewayIntegrationKind.OPENAI_EMBEDDINGS_V1.value,
        endpoint_url="https://api.deepinfra.com/v1/openai",
        api_key_ref="DEEPINFRA_API_KEY",
        model_name="BAAI/bge-m3",
        mode=LLMGatewayMode.CONVERSATION.value,
        params={},
    )
    operation = LLMOperation(code=OperationKey.RETRIEVAL_QUERY_EMBEDDING.value, gateway=gateway)

    response = adapter.complete(
        gateway=gateway,
        operation=operation,
        prompt_messages=[
            {"role": "system", "content": "Return JSON only"},
            {"role": "user", "content": '{"query":"stress management"}'},
        ],
    )

    request = transport.requests[0]
    assert request.url.endswith("/embeddings")
    assert request.json["model"] == "BAAI/bge-m3"
    assert request.json["input"] == "stress management"
    assert response.text == '{"embedding": [0.1, 0.2, 0.3]}'
    assert response.input_tokens == 7


def test_local_stub_adapter_requires_allow_stub_flag() -> None:
    """Local stub routing fails closed unless the gateway opts in explicitly."""

    turn = create_turn()
    gateway = LLMGatewayConfig.objects.create(
        display_name="Prod Stub",
        integration_kind=LLMGatewayIntegrationKind.OPENAI_COMPATIBLE.value,
        endpoint_url="https://api.deepinfra.com/v1/openai",
        api_key_ref="PROD_KEY",
        model_name="deepseek-ai/DeepSeek-V3",
        mode=LLMGatewayMode.CONVERSATION.value,
        params={"adapter": "local_stub"},
        is_active=True,
    )
    LLMOperation.objects.create(code="prod_stub_operation", description="Prod stub", gateway=gateway)

    with pytest.raises(LLMGatewayConfigurationError) as excinfo:
        LLMGateway().complete(
            operation_key="prod_stub_operation",
            turn=turn,
            prompt_messages=[{"role": "user", "content": "hello"}],
        )

    assert excinfo.value.code == LLM_GATEWAY_CONFIG_INVALID
    assert turn.llm_usage_events.count() == 0


def test_llm_usage_query_service_aggregates_by_day_and_filters() -> None:
    """Usage query service groups events by day and canonical filters."""

    supplier_name = "provider-a"
    model_name = "model-a"
    another_model_name = "model-b"
    turn_one = create_turn()
    turn_two = create_turn()

    LLMUsageEvent.objects.create(
        turn=turn_one,
        operation_key=OperationKey.FULL_REASONING.value,
        supplier_name=supplier_name,
        model_name=model_name,
        input_tokens=3,
        cached_input_tokens=1,
        output_tokens=2,
        cache_write_tokens=0,
        latency_ms=10,
        status=LLMUsageStatus.SUCCESS.value,
        error_code="",
    )
    LLMUsageEvent.objects.create(
        turn=turn_two,
        operation_key=OperationKey.RESPONSE_GENERATION.value,
        supplier_name=supplier_name,
        model_name=another_model_name,
        input_tokens=2,
        cached_input_tokens=0,
        output_tokens=4,
        cache_write_tokens=1,
        latency_ms=12,
        status=LLMUsageStatus.SUCCESS.value,
        error_code="",
    )

    service = LLMUsageQueryService()
    today = timezone.localdate()
    filtered = service.daily_summary(
        day=today,
        supplier_name=supplier_name,
        model_name=model_name,
        operation_key=OperationKey.FULL_REASONING.value,
    )
    unfiltered = service.daily_summary(day=today, supplier_name=supplier_name)

    assert filtered.event_count == 1
    assert filtered.total_billable_tokens == 6
    assert unfiltered.event_count == 2
    assert unfiltered.total_billable_tokens == 13


def test_llm_usage_query_service_summarizes_gateway_rows_for_admin_report() -> None:
    """Usage query service returns per-gateway report rows from runtime usage events."""

    turn_one = create_turn()
    turn_two = create_turn()

    LLMGateway().complete(
        operation_key=OperationKey.FULL_REASONING,
        turn=turn_one,
        prompt_messages=[{"role": "user", "content": "hello one"}],
    )
    LLMGateway().complete(
        operation_key=OperationKey.RESPONSE_GENERATION,
        turn=turn_two,
        prompt_messages=[{"role": "user", "content": "hello two"}],
    )

    service = LLMUsageQueryService()
    queryset = LLMUsageEvent.objects.all()
    totals = service.summarize_totals_from_queryset(queryset)
    rows = service.summarize_gateways_from_queryset(queryset)
    operation_rows = service.summarize_operations_from_queryset(queryset)
    gateway_choices = service.gateway_name_choices_from_queryset(queryset)

    assert totals.event_count == 2
    assert totals.success_count == 2
    assert totals.failed_count == 0
    assert totals.total_billable_tokens > 0
    assert rows
    assert rows[0].gateway_name == "Local Stub Gateway"
    assert rows[0].event_count == 2
    assert operation_rows
    assert {row.operation_key for row in operation_rows} == {
        OperationKey.FULL_REASONING.value,
        OperationKey.RESPONSE_GENERATION.value,
    }
    assert "Local Stub Gateway" in gateway_choices


def test_llm_usage_admin_registration_has_operational_filters() -> None:
    """Django admin exposes usage events with useful filtering and search."""

    admin = site._registry[LLMUsageEvent]

    assert admin.list_display == (
        "created_at",
        "turn",
        "operation_key",
        "supplier_name",
        "model_name",
        "status",
        "total_billable_tokens",
        "latency_ms",
    )
    assert admin.list_filter == ("operation_key", "status", "supplier_name", "model_name", "created_at")
    assert admin.date_hierarchy == "created_at"
    assert admin.search_fields == ("turn__id", "supplier_name", "model_name", "operation_key")
    assert (
        admin.change_list_template
        == "admin/llm_ops/llmusageevent/change_list.html"
    )
    assert "created_at" in admin.readonly_fields
    assert "operation_key" in admin.readonly_fields


def test_llm_gateway_admin_registration_exposes_gateway_and_operations() -> None:
    """Django admin exposes the canonical gateway and operation tables."""

    gateway_admin = site._registry[LLMGatewayConfig]
    operation_admin = site._registry[LLMOperation]

    assert gateway_admin.list_display == (
        "display_name",
        "integration_kind",
        "model_name",
        "mode",
        "is_active",
        "created_at",
    )
    assert gateway_admin.list_filter == ("integration_kind", "mode", "is_active")
    assert operation_admin.list_display == ("code", "description", "gateway", "routing_health", "is_active", "created_at")
    assert operation_admin.list_filter[0] == "is_active"
    assert operation_admin.list_filter[1] == "gateway"
    assert "gateway__display_name" in operation_admin.search_fields


def test_runtime_orchestrator_maps_gateway_failure_to_runtime_error() -> None:
    """Runtime stream surfaces gateway failures using canonical error event envelopes."""

    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    request = make_guest_request(guest=guest)
    gate_result = RuntimeOrchestrator().gate.run(request=request, data={"message": "hello world"})

    assert gate_result.passed is True
    chunks = list(
        RuntimeOrchestrator(llm_gateway=ConfigurationMissingGateway()).stream(
            gate_result,
        )
    )

    turn = ChatTurn.objects.filter(guest_identity=guest).latest("created_at")

    assert any("event: error" in chunk for chunk in chunks)
    assert any(f'"error": "{LLM_GATEWAY_CONFIG_MISSING}"' in chunk for chunk in chunks)
    assert any('"status_code": 500' in chunk for chunk in chunks)
    assert turn.status == TurnStatus.FAILED.value
    assert turn.step12_finalization_status == Step12FinalizationStatus.FAILED.value
    assert turn.usage_accounting_status == UsageAccountingStatus.FAILED.value
    assert turn.runtime_metadata["error"] == LLM_GATEWAY_CONFIG_MISSING


def test_gateway_consume_failure_writes_operational_log_and_keeps_runtime_alive() -> None:
    """Quota consume failures are logged to DB without breaking successful completions."""

    turn = create_turn()
    gateway = LLMGateway()

    with patch.object(gateway.quota_service, "consume_tokens", side_effect=RuntimeError("db write failed")):
        completion = gateway.complete(
            operation_key=OperationKey.RESPONSE_GENERATION,
            turn=turn,
            prompt_messages=[{"role": "user", "content": "hello"}],
        )

    assert completion.text
    assert turn.llm_usage_events.count() == 1
    op_log = OperationalLog.objects.get(event_key="quota_realtime_consume_failed", turn=turn)
    assert op_log.level == "error"
    assert op_log.component == "llm_ops.gateway"
    assert op_log.context["operation_key"] == OperationKey.RESPONSE_GENERATION.value
    assert op_log.context["tokens"] >= 1


def test_runtime_orchestrator_marks_step12_failed_on_unhandled_exception() -> None:
    """Step 12 crash after done must release the gate barrier without failing the turn.

    The response was already delivered to the client before Step 12 ran, so the turn
    stays completed. Only the finalization barrier must be released to FAILED so the
    next turn is not permanently blocked.
    """

    guest = GuestIdentity.objects.create()
    ConsentService().accept(guest_identity=guest)
    request = make_guest_request(guest=guest)
    gate_result = RuntimeOrchestrator().gate.run(request=request, data={"message": "hello world"})
    orchestrator = RuntimeOrchestrator()

    with patch.object(orchestrator, "_post_turn_finalization", side_effect=RuntimeError("boom")):
        events = list(orchestrator.stream(gate_result))  # exception is absorbed, not re-raised

    turn = ChatTurn.objects.filter(guest_identity=guest).latest("created_at")
    # Response was delivered before Step 12 ran — turn stays completed.
    assert turn.status == TurnStatus.COMPLETED.value
    # Barrier released so the next turn is not permanently blocked.
    assert turn.step12_finalization_status == Step12FinalizationStatus.FAILED.value
    # done event was emitted to the client despite Step 12 crashing.
    assert any("done" in event for event in events)
