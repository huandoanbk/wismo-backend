"""LLM Gateway routing with operation registry and provider adapters."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from llm_ops.errors import (
    LLM_GATEWAY_CONFIG_INVALID,
    LLM_GATEWAY_CONFIG_MISSING,
    LLM_GATEWAY_PROVIDER_ERROR,
    LLM_GATEWAY_PROVIDER_UNAVAILABLE,
    LLMGatewayConfigurationError,
    LLMGatewayError,
    LLMGatewayProviderError,
    LLMGatewayProviderUnavailableError,
)
from llm_ops.models import LLMGatewayConfig, LLMOperation, LLMUsageEvent
from llm_ops.providers import (
    AnthropicNativeLLMAdapter,
    AzureOpenAILLMAdapter,
    LLMProviderAdapter,
    LocalStubLLMAdapter,
    OpenAICompatibleLLMAdapter,
    OpenAIEmbeddingsLLMAdapter,
    OpenAINativeLLMAdapter,
)
from runtime.operational_logs import record_operational_log
from runtime.services import QuotaService
from wismo.contracts.enums import (
    LLMGatewayIntegrationKind,
    LLMGatewayMode,
    LLMUsageStatus,
    OperationKey,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMCompletion:
    """Text result returned by one LLM operation."""

    text: str
    usage_event: LLMUsageEvent


class LLMGateway:
    """Single entrypoint for runtime LLM operations."""

    def __init__(self, adapter_registry: dict[str, LLMProviderAdapter] | None = None) -> None:
        """Create a gateway with injectable provider adapters."""

        self.adapter_registry = self._default_adapter_registry() if adapter_registry is None else adapter_registry
        self.quota_service = QuotaService()
        self._trace_recorder: Callable[[dict[str, Any]], None] | None = None

    def set_trace_recorder(self, recorder: Callable[[dict[str, Any]], None] | None) -> None:
        """Set or clear optional runtime trace recorder for LLM calls."""

        self._trace_recorder = recorder

    def get_trace_recorder(self) -> Callable[[dict[str, Any]], None] | None:
        """Return the current LLM trace recorder."""

        return self._trace_recorder

    def complete(
        self,
        *,
        operation_key: OperationKey | str,
        turn,
        prompt_messages: list[dict[str, Any]],
    ) -> LLMCompletion:
        """Run an LLM operation through configured routing and record usage.

        response_generation supports optional fallback_gateway routing and only
        triggers fallback when the primary call fails with a gateway error.
        """

        operation_code = operation_key.value if isinstance(operation_key, OperationKey) else str(operation_key)
        operation = self._resolve_operation(operation_code)
        try:
            return self._complete_once(
                operation=operation,
                gateway=operation.gateway,
                turn=turn,
                prompt_messages=prompt_messages,
            )
        except LLMGatewayError as primary_exc:
            fallback_gateway = operation.fallback_gateway
            if (
                operation.code == OperationKey.RESPONSE_GENERATION.value
                and fallback_gateway is not None
                and self._is_gateway_error(primary_exc)
            ):
                logger.warning(
                    "llm_gateway_fallback_attempt operation=%s primary_error=%s primary_status=%s turn_id=%s",
                    operation.code,
                    primary_exc.code,
                    primary_exc.status_code,
                    str(turn.id) if turn is not None else "none",
                )
                record_operational_log(
                    event_key="llm_fallback_triggered",
                    level="warning",
                    component="llm_ops.gateway",
                    message=f"LLM fallback triggered: {operation.code} — primary error {primary_exc.code}",
                    context={
                        "operation": operation.code,
                        "primary_error": primary_exc.code,
                        "primary_status": primary_exc.status_code,
                    },
                    turn=turn,
                )
                try:
                    return self._complete_once(
                        operation=operation,
                        gateway=fallback_gateway,
                        turn=turn,
                        prompt_messages=prompt_messages,
                    )
                except LLMGatewayError as fallback_exc:
                    logger.error(
                        "llm_gateway_fallback_failed operation=%s fallback_error=%s fallback_status=%s turn_id=%s",
                        operation.code,
                        fallback_exc.code,
                        fallback_exc.status_code,
                        str(turn.id) if turn is not None else "none",
                    )
                    raise fallback_exc
            raise

    def _default_adapter_registry(self) -> dict[str, LLMProviderAdapter]:
        """Return the built-in adapter registry for canonical integration kinds."""

        return {
            LLMGatewayIntegrationKind.OPENAI_COMPATIBLE.value: OpenAICompatibleLLMAdapter(),
            LLMGatewayIntegrationKind.OPENAI_EMBEDDINGS_V1.value: OpenAIEmbeddingsLLMAdapter(),
            LLMGatewayIntegrationKind.ANTHROPIC_NATIVE.value: AnthropicNativeLLMAdapter(),
            LLMGatewayIntegrationKind.AZURE_OPENAI_V1.value: AzureOpenAILLMAdapter(),
            LLMGatewayIntegrationKind.OPENAI_NATIVE.value: OpenAINativeLLMAdapter(),
            "local_stub": LocalStubLLMAdapter(),
        }

    @staticmethod
    def _is_gateway_error(error: LLMGatewayError) -> bool:
        """Return whether an error should trigger response-generation fallback."""

        return isinstance(error, (LLMGatewayProviderUnavailableError, LLMGatewayProviderError))

    def _complete_once(
        self,
        *,
        operation: LLMOperation,
        gateway: LLMGatewayConfig | None,
        turn,
        prompt_messages: list[dict[str, Any]],
    ) -> LLMCompletion:
        """Run one operation against one gateway without trying fallback."""

        started = perf_counter()
        self._validate_gateway(operation=operation, gateway=gateway)
        assert gateway is not None  # for type checkers after _validate_gateway guard

        try:
            adapter = self._resolve_adapter(gateway)
            provider_response = adapter.complete(
                gateway=gateway,
                operation=operation,
                prompt_messages=prompt_messages,
            )
        except LLMGatewayError as exc:
            latency_ms = int((perf_counter() - started) * 1000)
            self._record_usage_event(
                turn=turn,
                operation_code=operation.code,
                gateway=gateway,
                input_tokens=0,
                cached_input_tokens=0,
                output_tokens=0,
                cache_write_tokens=0,
                latency_ms=latency_ms,
                status=LLMUsageStatus.FAILED.value,
                error_code=exc.code,
            )
            logger.error(
                "llm_gateway_failed operation=%s supplier=%s model=%s error_code=%s latency_ms=%s turn_id=%s",
                operation.code,
                gateway.display_name,
                gateway.model_name,
                exc.code,
                latency_ms,
                str(turn.id) if turn is not None else "none",
            )
            self._emit_trace(
                operation_code=operation.code,
                gateway=gateway,
                prompt_messages=prompt_messages,
                status=LLMUsageStatus.FAILED.value,
                latency_ms=latency_ms,
                error_code=exc.code,
                error_status=exc.status_code,
                error_message=exc.message,
            )
            if isinstance(exc, LLMGatewayProviderUnavailableError):
                record_operational_log(
                    event_key="llm_provider_unavailable",
                    component="llm_ops.gateway",
                    message=f"LLM provider unavailable: {operation.code} via {gateway.display_name} ({latency_ms}ms)",
                    context={
                        "operation": operation.code,
                        "supplier": gateway.display_name,
                        "model": gateway.model_name,
                        "latency_ms": latency_ms,
                        "error": exc.code,
                    },
                    turn=turn,
                )
            elif isinstance(exc, LLMGatewayProviderError):
                record_operational_log(
                    event_key="llm_provider_error",
                    component="llm_ops.gateway",
                    message=f"LLM provider error: {operation.code} via {gateway.display_name} ({latency_ms}ms)",
                    context={
                        "operation": operation.code,
                        "supplier": gateway.display_name,
                        "model": gateway.model_name,
                        "latency_ms": latency_ms,
                        "error": exc.code,
                        "status_code": exc.status_code,
                    },
                    turn=turn,
                )
            raise
        except Exception as exc:  # pragma: no cover - defensive safety net
            latency_ms = int((perf_counter() - started) * 1000)
            self._record_usage_event(
                turn=turn,
                operation_code=operation.code,
                gateway=gateway,
                input_tokens=0,
                cached_input_tokens=0,
                output_tokens=0,
                cache_write_tokens=0,
                latency_ms=latency_ms,
                status=LLMUsageStatus.FAILED.value,
                error_code=LLM_GATEWAY_PROVIDER_ERROR,
            )
            logger.exception(
                "llm_gateway_unexpected_error operation=%s supplier=%s model=%s latency_ms=%s turn_id=%s",
                operation.code,
                gateway.display_name,
                gateway.model_name,
                latency_ms,
                str(turn.id) if turn is not None else "none",
            )
            self._emit_trace(
                operation_code=operation.code,
                gateway=gateway,
                prompt_messages=prompt_messages,
                status=LLMUsageStatus.FAILED.value,
                latency_ms=latency_ms,
                error_code=LLM_GATEWAY_PROVIDER_ERROR,
                error_status=500,
                error_message=str(exc),
            )
            raise LLMGatewayProviderError(message=str(exc)) from exc

        latency_ms = int((perf_counter() - started) * 1000)
        usage_event = self._record_usage_event(
            turn=turn,
            operation_code=operation.code,
            gateway=gateway,
            input_tokens=provider_response.input_tokens,
            cached_input_tokens=provider_response.cached_input_tokens,
            output_tokens=provider_response.output_tokens,
            cache_write_tokens=provider_response.cache_write_tokens,
            latency_ms=latency_ms,
            status=LLMUsageStatus.SUCCESS.value,
            error_code="",
        )
        self._consume_quota_realtime(
            turn=turn,
            tokens=usage_event.total_billable_tokens,
            operation_key=operation.code,
        )
        self._emit_trace(
            operation_code=operation.code,
            gateway=gateway,
            prompt_messages=prompt_messages,
            status=LLMUsageStatus.SUCCESS.value,
            latency_ms=latency_ms,
            response_text=provider_response.text,
            usage={
                "input_tokens": provider_response.input_tokens,
                "cached_input_tokens": provider_response.cached_input_tokens,
                "output_tokens": provider_response.output_tokens,
                "cache_write_tokens": provider_response.cache_write_tokens,
            },
        )
        return LLMCompletion(text=provider_response.text, usage_event=usage_event)

    def _resolve_operation(self, operation_code: str) -> LLMOperation:
        """Resolve the active operation registry entry for one call."""

        operation = LLMOperation.objects.select_related("gateway", "fallback_gateway").filter(code=operation_code).first()
        if operation is None:
            raise LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_MISSING)
        if not operation.is_active:
            raise LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_INVALID)
        return operation

    def _validate_gateway(self, *, operation: LLMOperation, gateway: LLMGatewayConfig | None) -> None:
        """Fail closed when an active operation has no valid gateway binding."""

        if not operation.is_active:
            raise LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_MISSING)
        if gateway is None or not gateway.is_active:
            raise LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_INVALID)
        if not gateway.display_name or not gateway.endpoint_url or not gateway.api_key_ref or not gateway.model_name:
            raise LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_INVALID)
        if gateway.integration_kind not in {
            LLMGatewayIntegrationKind.OPENAI_COMPATIBLE.value,
            LLMGatewayIntegrationKind.OPENAI_EMBEDDINGS_V1.value,
            LLMGatewayIntegrationKind.ANTHROPIC_NATIVE.value,
            LLMGatewayIntegrationKind.AZURE_OPENAI_V1.value,
            LLMGatewayIntegrationKind.OPENAI_NATIVE.value,
        }:
            raise LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_INVALID)
        if gateway.mode not in {
            LLMGatewayMode.SINGLE_MESSAGE.value,
            LLMGatewayMode.CONVERSATION.value,
        }:
            raise LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_INVALID)
        if gateway.params.get("adapter") == "local_stub" and not gateway.params.get("allow_stub"):
            raise LLMGatewayConfigurationError(LLM_GATEWAY_CONFIG_INVALID)

    def _resolve_adapter(self, gateway: LLMGatewayConfig) -> LLMProviderAdapter:
        """Return a normalized adapter for the configured gateway."""

        adapter_name = str(gateway.params.get("adapter") or gateway.integration_kind)
        adapter = self.adapter_registry.get(adapter_name)
        if adapter is None:
            raise LLMGatewayProviderUnavailableError(LLM_GATEWAY_PROVIDER_UNAVAILABLE)
        return adapter

    def _record_usage_event(
        self,
        *,
        turn,
        operation_code: str,
        gateway: LLMGatewayConfig,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int,
        latency_ms: int,
        status: str,
        error_code: str,
    ) -> LLMUsageEvent:
        """Persist a canonical usage event for one gateway call."""

        return LLMUsageEvent.objects.create(
            turn=turn,
            operation_key=operation_code,
            supplier_name=gateway.display_name,
            model_name=gateway.model_name,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            latency_ms=latency_ms,
            status=status,
            error_code=error_code,
        )

    def _consume_quota_realtime(self, *, turn, tokens: int, operation_key: str) -> None:
        """Consume quota immediately for one successful LLM call."""

        try:
            owner_type = "unknown"
            owner_id = ""
            if turn.user_id is not None:
                window = self.quota_service.current_for_identity(user=turn.user)
                owner_type = "user"
                owner_id = str(turn.user_id)
            elif turn.guest_identity_id is not None:
                window = self.quota_service.current_for_identity(guest_identity=turn.guest_identity)
                owner_type = "guest"
                owner_id = str(turn.guest_identity_id)
            else:
                return
            self.quota_service.consume_tokens(window, max(tokens, 0))
        except Exception:
            logger.exception(
                "quota_realtime_consume_failed turn_id=%s owner_type=%s owner_id=%s tokens=%s operation_key=%s",
                str(turn.id),
                owner_type,
                owner_id,
                tokens,
                operation_key,
            )
            record_operational_log(
                event_key="quota_realtime_consume_failed",
                level="error",
                component="llm_ops.gateway",
                message="Realtime quota consume failed after successful LLM usage event.",
                context={
                    "turn_id": str(turn.id),
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "tokens": max(tokens, 0),
                    "operation_key": operation_key,
                },
                turn=turn,
            )
            # Do not block runtime on quota persistence hiccups in MVP.
            return

    def _emit_trace(
        self,
        *,
        operation_code: str,
        gateway: LLMGatewayConfig,
        prompt_messages: list[dict[str, Any]],
        status: str,
        latency_ms: int,
        response_text: str | None = None,
        usage: dict[str, int] | None = None,
        error_code: str | None = None,
        error_status: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Emit one LLM call trace payload to the configured recorder."""

        if self._trace_recorder is None:
            return

        payload: dict[str, Any] = {
            "operation_key": operation_code,
            "supplier_name": gateway.display_name,
            "model_name": gateway.model_name,
            "status": status,
            "latency_ms": latency_ms,
            "prompt_messages": copy.deepcopy(prompt_messages),
        }
        if response_text is not None:
            payload["response_text"] = response_text
        if usage is not None:
            payload["usage"] = usage
        if error_code is not None:
            payload["error_code"] = error_code
        if error_status is not None:
            payload["error_status"] = error_status
        if error_message:
            payload["error_message"] = error_message

        try:
            self._trace_recorder(payload)
        except Exception:  # pragma: no cover - observability hook must never fail runtime.
            logger.exception("llm_trace_recorder_failed")
