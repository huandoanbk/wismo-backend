"""Provider adapters and wire serializers for LLM gateway integrations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from llm_ops.errors import LLMGatewayProviderError
from llm_ops.models import LLMGatewayConfig, LLMOperation
from wismo.contracts.enums import LLMGatewayMode, OperationKey

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMProviderRequest:
    """Prepared HTTP request for one provider call."""

    method: str
    url: str
    headers: dict[str, str]
    json: dict[str, Any]


@dataclass(frozen=True)
class LLMProviderResult:
    """Normalized HTTP response returned by a provider transport."""

    status_code: int
    json_body: dict[str, Any]
    text: str


class LLMProviderTransport(Protocol):
    """Transport protocol for provider adapters."""

    def send(self, request: LLMProviderRequest) -> LLMProviderResult:
        """Send one serialized provider request."""


class RequestsTransport:
    """Requests-based transport for real provider HTTP calls."""

    def __init__(self, timeout_seconds: int = 60) -> None:
        """Create a transport with a fixed timeout."""

        self.timeout_seconds = timeout_seconds

    def send(self, request: LLMProviderRequest) -> LLMProviderResult:
        """Send an HTTP request and normalize the response."""

        response = requests.request(
            method=request.method,
            url=request.url,
            headers=request.headers,
            json=request.json,
            timeout=self.timeout_seconds,
        )
        json_body: dict[str, Any]
        try:
            json_body = response.json()
        except ValueError:
            json_body = {}
        return LLMProviderResult(status_code=response.status_code, json_body=json_body, text=response.text)


class LLMProviderAdapter:
    """Protocol-like base class for one provider integration."""

    def __init__(self, transport: LLMProviderTransport | None = None) -> None:
        """Create an adapter with an optional custom transport."""

        self.transport = transport or RequestsTransport()

    def complete(
        self,
        *,
        gateway: LLMGatewayConfig,
        operation: LLMOperation,
        prompt_messages: list[dict[str, Any]],
    ) -> LLMProviderResponse:
        """Serialize input, call the provider, and normalize the output."""

        request = self.build_request(gateway=gateway, operation=operation, prompt_messages=prompt_messages)
        result = self.transport.send(request)
        if result.status_code >= 400:
            logger.error(
                "llm_provider_http_error operation=%s supplier=%s status=%s body=%.500s",
                operation.code,
                gateway.display_name,
                result.status_code,
                result.text,
            )
            raise LLMGatewayProviderError(message=result.text)
        return self.parse_response(result.json_body)

    def build_request(
        self,
        *,
        gateway: LLMGatewayConfig,
        operation: LLMOperation,
        prompt_messages: list[dict[str, Any]],
    ) -> LLMProviderRequest:
        """Build a provider-specific request payload."""

        raise NotImplementedError

    def parse_response(self, payload: dict[str, Any]) -> LLMProviderResponse:
        """Parse a provider response into the normalized gateway shape."""

        raise NotImplementedError


@dataclass(frozen=True)
class LLMProviderResponse:
    """Normalized provider response returned by one adapter call."""

    text: str
    input_tokens: int
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0


def _stringify_content(content: Any) -> str:
    """Return a stable string representation for message content."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if "text" in block:
                    parts.append(str(block["text"]))
                elif "content" in block:
                    parts.append(str(block["content"]))
            else:
                parts.append(str(block))
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    return str(content)


def _normalize_messages(prompt_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only role/content message fields in provider payloads."""

    normalized: list[dict[str, Any]] = []
    for message in prompt_messages:
        normalized.append(
            {
                "role": str(message.get("role", "user")),
                "content": _stringify_content(message.get("content", "")),
            }
        )
    return normalized


def _collapse_single_message(prompt_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse a conversation into one user message."""

    lines: list[str] = []
    for message in prompt_messages:
        role = str(message.get("role", "user")).upper()
        content = _stringify_content(message.get("content", ""))
        if content:
            lines.append(f"{role}: {content}")
    return [{"role": "user", "content": "\n".join(lines)}]


def _split_anthropic_messages(
    prompt_messages: list[dict[str, Any]],
    *,
    single_message: bool,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Hoist system/developer instructions for Anthropic wire payloads."""

    system_lines: list[str] = []
    conversation_lines: list[str] = []
    converted_messages: list[dict[str, Any]] = []

    for message in prompt_messages:
        role = str(message.get("role", "user"))
        content = _stringify_content(message.get("content", ""))
        if role in {"system", "developer"}:
            if content:
                system_lines.append(content)
            continue

        if single_message:
            if content:
                conversation_lines.append(f"{role.upper()}: {content}")
            continue

        converted_messages.append({"role": role, "content": content})

    if single_message:
        converted_messages = [{"role": "user", "content": "\n".join(conversation_lines)}]

    system_text = "\n".join(system_lines) if system_lines else None
    return system_text, converted_messages


def _estimate_tokens(prompt_messages: list[dict[str, Any]]) -> int:
    """Estimate token count without an external tokenizer dependency."""

    text = " ".join(_stringify_content(message.get("content", "")) for message in prompt_messages)
    return max(1, len(text.split()))


def _resolve_max_tokens(params: dict[str, Any], default_value: int = 512) -> int:
    """Pick the gateway max token setting from canonical params."""

    for key in ("max_output_tokens", "max_tokens", "output_tokens"):
        value = params.get(key)
        if isinstance(value, int) and value > 0:
            return value
    return default_value


def _openai_style_payload(
    *,
    gateway: LLMGatewayConfig,
    prompt_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an OpenAI-style chat completions payload."""

    params = dict(gateway.params)
    if gateway.mode == LLMGatewayMode.SINGLE_MESSAGE.value:
        messages = _collapse_single_message(prompt_messages)
    else:
        messages = _normalize_messages(prompt_messages)

    payload: dict[str, Any] = {
        "model": gateway.model_name,
        "messages": messages,
    }
    max_tokens = _resolve_max_tokens(params)
    if max_tokens:
        payload["max_tokens"] = max_tokens
    for key in (
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "stop",
        "response_format",
        "tools",
        "tool_choice",
        "service_tier",
        "reasoning_effort",
        "seed",
        "metadata",
        "stream",
        "logprobs",
    ):
        value = params.get(key)
        if value is not None:
            payload[key] = value
    extra_body = params.get("extra_body")
    if isinstance(extra_body, dict):
        payload.update(extra_body)
    return payload


def _openai_style_headers(gateway: LLMGatewayConfig) -> dict[str, str]:
    """Build headers for OpenAI-style providers."""

    api_key = gateway.params.get("api_key")
    if api_key is None:
        api_key = gateway.params.get("api_key_value")
    if api_key is None:
        api_key = gateway.params.get("api_key_ref")
    headers = {
        "Authorization": f"Bearer {api_key or gateway.api_key_ref}",
        "Content-Type": "application/json",
    }
    extra_headers = gateway.params.get("headers")
    if isinstance(extra_headers, dict):
        headers.update({str(key): str(value) for key, value in extra_headers.items()})
    return headers


class OpenAICompatibleLLMAdapter(LLMProviderAdapter):
    """Adapter for OpenAI-compatible wire contracts."""

    def build_request(
        self,
        *,
        gateway: LLMGatewayConfig,
        operation: LLMOperation,
        prompt_messages: list[dict[str, Any]],
    ) -> LLMProviderRequest:
        """Build an OpenAI-compatible chat completions request."""

        return LLMProviderRequest(
            method="POST",
            url=f"{gateway.endpoint_url.rstrip('/')}/chat/completions",
            headers=_openai_style_headers(gateway),
            json=_openai_style_payload(gateway=gateway, prompt_messages=prompt_messages),
        )

    def parse_response(self, payload: dict[str, Any]) -> LLMProviderResponse:
        """Normalize an OpenAI-compatible response."""

        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = payload.get("usage") or {}
        return LLMProviderResponse(
            text=_stringify_content(message.get("content", "")),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )


class OpenAINativeLLMAdapter(OpenAICompatibleLLMAdapter):
    """Adapter for OpenAI/ChatGPT native wire contracts."""


class OpenAIEmbeddingsLLMAdapter(LLMProviderAdapter):
    """Adapter for OpenAI-compatible embeddings wire contracts."""

    def build_request(
        self,
        *,
        gateway: LLMGatewayConfig,
        operation: LLMOperation,
        prompt_messages: list[dict[str, Any]],
    ) -> LLMProviderRequest:
        """Build an OpenAI-compatible embeddings request."""

        _ = operation
        params = dict(gateway.params)
        payload: dict[str, Any] = {
            "model": gateway.model_name,
            "input": self._extract_input(prompt_messages),
        }
        for key in ("encoding_format", "dimensions", "user"):
            value = params.get(key)
            if value is not None:
                payload[key] = value
        extra_body = params.get("extra_body")
        if isinstance(extra_body, dict):
            payload.update(extra_body)
        return LLMProviderRequest(
            method="POST",
            url=f"{gateway.endpoint_url.rstrip('/')}/embeddings",
            headers=_openai_style_headers(gateway),
            json=payload,
        )

    def parse_response(self, payload: dict[str, Any]) -> LLMProviderResponse:
        """Normalize an embeddings response into gateway text+usage shape."""

        data = payload.get("data")
        vector: list[float] = []
        if isinstance(data, list) and data and isinstance(data[0], dict):
            raw = data[0].get("embedding")
            if isinstance(raw, list):
                vector = [float(item) for item in raw]
        usage = payload.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or max(total_tokens - input_tokens, 0))
        return LLMProviderResponse(
            text=json.dumps({"embedding": vector}, ensure_ascii=False),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @staticmethod
    def _extract_input(prompt_messages: list[dict[str, Any]]) -> str:
        """Extract embedding input text from prompt messages."""

        # Step 9 embedding call uses:
        # system: "Return JSON only..."
        # user: {"query":"..."}
        for message in reversed(prompt_messages):
            content = _stringify_content(message.get("content", ""))
            if not content:
                continue
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                parsed = None
            if isinstance(parsed, dict):
                query = parsed.get("query")
                if isinstance(query, str) and query.strip():
                    return query.strip()
            if str(message.get("role", "")).lower() == "user":
                return content
        return ""


class AzureOpenAILLMAdapter(OpenAICompatibleLLMAdapter):
    """Adapter for Azure OpenAI v1 chat completions wire contracts."""


class AnthropicNativeLLMAdapter(LLMProviderAdapter):
    """Adapter for Anthropic native Messages API."""

    def build_request(
        self,
        *,
        gateway: LLMGatewayConfig,
        operation: LLMOperation,
        prompt_messages: list[dict[str, Any]],
    ) -> LLMProviderRequest:
        """Build an Anthropic Messages API request."""

        single_message = gateway.mode == LLMGatewayMode.SINGLE_MESSAGE.value
        system_text, messages = _split_anthropic_messages(
            prompt_messages,
            single_message=single_message,
        )
        params = dict(gateway.params)
        payload: dict[str, Any] = {
            "model": gateway.model_name,
            "max_tokens": _resolve_max_tokens(params),
            "messages": messages,
        }
        if system_text:
            payload["system"] = system_text
        for key in ("temperature", "top_p", "stop_sequences", "metadata", "thinking"):
            value = params.get(key)
            if value is not None:
                payload[key] = value
        return LLMProviderRequest(
            method="POST",
            url=f"{gateway.endpoint_url.rstrip('/')}/messages",
            headers={
                "x-api-key": gateway.api_key_ref,
                "anthropic-version": str(gateway.params.get("anthropic_version", "2023-06-01")),
                "Content-Type": "application/json",
            },
            json=payload,
        )

    def parse_response(self, payload: dict[str, Any]) -> LLMProviderResponse:
        """Normalize an Anthropic response."""

        content = payload.get("content") or []
        text_blocks = [
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        usage = payload.get("usage") or {}
        return LLMProviderResponse(
            text="\n".join(block for block in text_blocks if block),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )


class LocalStubLLMAdapter(LLMProviderAdapter):
    """Deterministic local adapter used by dev and tests."""

    def __init__(self) -> None:
        """Create a deterministic adapter without HTTP dependencies."""

        super().__init__(transport=_LocalStubTransport())

    def build_request(
        self,
        *,
        gateway: LLMGatewayConfig,
        operation: LLMOperation,
        prompt_messages: list[dict[str, Any]],
    ) -> LLMProviderRequest:
        """Build a pseudo-request used for tests and fixtures."""

        return LLMProviderRequest(
            method="POST",
            url="local_stub://complete",
            headers={},
            json={
                "operation": operation.code,
                "messages": prompt_messages,
                "mode": gateway.mode,
            },
        )

    def parse_response(self, payload: dict[str, Any]) -> LLMProviderResponse:
        """Parse the deterministic local stub payload."""

        return LLMProviderResponse(
            text=str(payload.get("text", "")),
            input_tokens=int(payload.get("input_tokens") or 0),
            output_tokens=int(payload.get("output_tokens") or 0),
        )


class _LocalStubTransport:
    """Internal deterministic transport for dev/test usage."""

    def send(self, request: LLMProviderRequest) -> LLMProviderResult:
        """Return a predictable local stub response."""

        operation = str(request.json.get("operation", ""))
        messages = request.json.get("messages") or []
        input_tokens = _estimate_tokens(messages if isinstance(messages, list) else [])
        if operation == OperationKey.RESPONSE_GENERATION.value:
            text = "I received your message. What is the most important part you want me to understand next?"
        elif operation == OperationKey.RESPONSE_VALIDATION.value:
            text = '{"pass": true, "severity": "light", "error_codes": [], "rewrite_instruction": "", "fallback_recommended": null}'
        elif operation == OperationKey.LONG_TERM_MEMORY_EXTRACTOR.value:
            text = (
                '{"action":"no_update","active_segment_update":null,'
                '"closed_active_segment_update":null,"new_segment_update":null}'
            )
        else:
            text = "{}"
        output_tokens = max(1, len(text.split()))
        return LLMProviderResult(
            status_code=200,
            json_body={
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            text=text,
        )
