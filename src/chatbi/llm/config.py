"""Runtime wiring for the LLM Provider Gateway."""

from __future__ import annotations

from chatbi.core.runtime_config import RuntimeConfig
from chatbi.llm.gateway import LLMGateway
from chatbi.llm.providers import MockLLMProvider, OpenAIChatProvider
from chatbi.llm.types import LLMProvider, ModelRoute, ModelRouter
from chatbi.trace_events import TraceEventRecorder


def build_llm_client_from_runtime_config(
    runtime_config: RuntimeConfig,
    trace_event_recorder: TraceEventRecorder | None = None,
) -> LLMGateway:
    provider_name = runtime_config.llm_provider.strip().lower()
    provider = _provider_for(provider_name)
    sql_route = ModelRoute(
        task_type="sql_generation",
        provider=provider.provider_name,
        model_name=runtime_config.llm_model,
        timeout_ms=runtime_config.llm_timeout_ms,
        max_retries=runtime_config.llm_max_retries,
        backoff_ms=runtime_config.llm_backoff_ms,
    )
    answer_route = ModelRoute(
        task_type="answer_synthesis",
        provider=provider.provider_name,
        model_name=runtime_config.llm_model,
        timeout_ms=runtime_config.llm_timeout_ms,
        max_retries=runtime_config.llm_max_retries,
        backoff_ms=runtime_config.llm_backoff_ms,
    )
    return LLMGateway(
        providers={provider.provider_name: provider},
        router=ModelRouter(
            routes={
                "sql_generation": sql_route,
                "answer_synthesis": answer_route,
            },
            default_route=answer_route,
        ),
        trace_event_recorder=trace_event_recorder,
    )


def _provider_for(provider_name: str) -> LLMProvider:
    if provider_name == "mock":
        return MockLLMProvider()
    if provider_name == "openai":
        return OpenAIChatProvider()
    raise ValueError(f"Unsupported LLM provider: {provider_name}")
