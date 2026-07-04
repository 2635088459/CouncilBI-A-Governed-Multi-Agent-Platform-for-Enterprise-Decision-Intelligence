"""Provider-neutral LLM Gateway contracts for final-version spec FV-02."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


class LLMProviderError(RuntimeError):
    """Sanitized provider error safe to surface in internal warnings."""


class LLMTimeoutError(LLMProviderError):
    """Raised when a provider call exceeds its configured timeout budget."""


class LLMCircuitBreakerOpenError(LLMProviderError):
    """Raised when the LLM provider circuit is open."""


class LLMConfigurationError(ValueError):
    """Raised when a real provider is missing required secret configuration."""


@dataclass(frozen=True, slots=True)
class LLMRequest:
    task_type: str
    prompt_version: str
    messages: tuple[Mapping[str, str], ...]
    model_policy: Mapping[str, object]
    temperature: float
    max_tokens: int
    user_id: str
    org_id: str
    trace_id: str

    def __post_init__(self) -> None:
        if not self.task_type.strip():
            raise ValueError("task_type is required")
        if not self.prompt_version.strip():
            raise ValueError("prompt_version is required")
        if not self.messages:
            raise ValueError("messages are required")
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if not self.org_id.strip():
            raise ValueError("org_id is required")
        if not self.trace_id.startswith("trc_"):
            raise ValueError("trace_id must start with 'trc_'")
        if self.temperature < 0:
            raise ValueError("temperature must be greater than or equal to 0")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be greater than 0")


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model_name: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    latency_ms: int
    finish_reason: str
    safety_flags: tuple[str, ...] = ()
    raw_response_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("model_name is required")
        if not self.provider.strip():
            raise ValueError("provider is required")
        if self.prompt_tokens < 0 or self.completion_tokens < 0 or self.total_tokens < 0:
            raise ValueError("token counts must be greater than or equal to 0")
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("total_tokens must equal prompt_tokens plus completion_tokens")
        if self.estimated_cost < 0:
            raise ValueError("estimated_cost must be greater than or equal to 0")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be greater than or equal to 0")
        if not self.finish_reason.strip():
            raise ValueError("finish_reason is required")


@dataclass(frozen=True, slots=True)
class ModelRoute:
    task_type: str
    provider: str
    model_name: str
    timeout_ms: int
    max_retries: int = 1
    backoff_ms: int = 25
    prompt_token_cost_per_1k: float = 0.0
    completion_token_cost_per_1k: float = 0.0

    def __post_init__(self) -> None:
        if not self.task_type.strip():
            raise ValueError("task_type is required")
        if not self.provider.strip():
            raise ValueError("provider is required")
        if not self.model_name.strip():
            raise ValueError("model_name is required")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be greater than 0")
        if self.max_retries < 0:
            raise ValueError("max_retries must be greater than or equal to 0")
        if self.backoff_ms < 0:
            raise ValueError("backoff_ms must be greater than or equal to 0")


class ModelRouter:
    def __init__(
        self,
        routes: Mapping[str, ModelRoute] | None = None,
        default_route: ModelRoute | None = None,
    ) -> None:
        self._routes = dict(routes or {})
        self._default_route = default_route or ModelRoute(
            task_type="default",
            provider="mock",
            model_name="mock-chatbi-small",
            timeout_ms=1000,
        )

    def route_for(self, task_type: str) -> ModelRoute:
        return self._routes.get(task_type, self._default_route)


class LLMProvider(Protocol):
    provider_name: str

    def complete(self, request: LLMRequest, route: ModelRoute) -> LLMResponse:
        ...


class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse:
        ...


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    route: ModelRoute,
) -> float:
    return round(
        (prompt_tokens / 1000.0 * route.prompt_token_cost_per_1k)
        + (completion_tokens / 1000.0 * route.completion_token_cost_per_1k),
        8,
    )


def token_count_from_messages(messages: tuple[Mapping[str, str], ...]) -> int:
    text = " ".join(message.get("content", "") for message in messages)
    return max(1, len(text.split()))
