"""Error helpers for the LLM gateway foundation."""

from __future__ import annotations

LLM_GATEWAY_CONFIG_MISSING = "llm_gateway_config_missing"
LLM_GATEWAY_CONFIG_INVALID = "llm_gateway_config_invalid"
LLM_GATEWAY_PROVIDER_UNAVAILABLE = "llm_gateway_provider_unavailable"
LLM_GATEWAY_PROVIDER_ERROR = "llm_gateway_provider_error"
LLM_RESPONSE_GENERATION_FAILED = "response_generation_failed"


class LLMGatewayError(Exception):
    """Structured domain error for LLM gateway failures."""

    def __init__(self, code: str, status_code: int = 500, message: str = "") -> None:
        """Create a canonical LLM gateway error."""

        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.message = message


class LLMGatewayConfigurationError(LLMGatewayError):
    """Error raised when operation routing configuration is missing or invalid."""

    def __init__(self, code: str, message: str = "") -> None:
        """Create a canonical configuration error."""

        super().__init__(code, 500, message)


class LLMGatewayProviderUnavailableError(LLMGatewayError):
    """Error raised when a configured provider adapter is unavailable."""

    def __init__(self, code: str = LLM_GATEWAY_PROVIDER_UNAVAILABLE, message: str = "") -> None:
        """Create a canonical provider-unavailable error."""

        super().__init__(code, 503, message)


class LLMGatewayProviderError(LLMGatewayError):
    """Error raised when a provider adapter fails during a valid request."""

    def __init__(self, code: str = LLM_GATEWAY_PROVIDER_ERROR, message: str = "") -> None:
        """Create a canonical provider error."""

        super().__init__(code, 502, message)
