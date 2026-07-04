"""Observable LLM Gateway with model routing, retry, timeout, and cost tracking."""

from __future__ import annotations

import concurrent.futures
import time
from typing import Mapping

from chatbi.llm.store import InMemoryLLMCostStore
from chatbi.llm.types import (
    LLMCircuitBreakerOpenError,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    ModelRouter,
)
from chatbi.resilience import CircuitBreaker, CircuitBreakerOpenError
from chatbi.trace_events import TraceEvent, TraceEventRecorder, TraceEventStatus


class LLMGateway:
    def __init__(
        self,
        providers: Mapping[str, LLMProvider],
        router: ModelRouter | None = None,
        trace_event_recorder: TraceEventRecorder | None = None,
        cost_store: InMemoryLLMCostStore | None = None,
        circuit_breakers: Mapping[str, CircuitBreaker] | None = None,
    ) -> None:
        if not providers:
            raise ValueError("at least one LLM provider is required")
        self._providers = dict(providers)
        self._router = router or ModelRouter()
        self._trace_event_recorder = trace_event_recorder or TraceEventRecorder(
            service="llm-gateway"
        )
        self._cost_store = cost_store or InMemoryLLMCostStore()
        self._circuit_breakers = dict(circuit_breakers or {})

    @property
    def cost_store(self) -> InMemoryLLMCostStore:
        return self._cost_store

    @property
    def trace_event_recorder(self) -> TraceEventRecorder:
        return self._trace_event_recorder

    def circuit_breaker_for(self, provider_name: str) -> CircuitBreaker:
        breaker = self._circuit_breakers.get(provider_name)
        if breaker is None:
            breaker = CircuitBreaker()
            self._circuit_breakers[provider_name] = breaker
        return breaker

    def complete(self, request: LLMRequest) -> LLMResponse:
        route = self._router.route_for(request.task_type)
        provider = self._providers.get(route.provider)
        if provider is None:
            raise LLMProviderError("Provider is not configured.")

        started_event = self._trace_event_recorder.start(
            trace_id=request.trace_id,
            span_name=f"llm.{request.task_type}",
        )
        breaker = self.circuit_breaker_for(route.provider)
        try:
            breaker.before_call()
        except CircuitBreakerOpenError as exc:
            self._trace_event_recorder.complete(
                started_event,
                status=TraceEventStatus.DEGRADED,
                metadata={
                    "provider": route.provider,
                    "model": route.model_name,
                    "task_type": request.task_type,
                    "attempts": 0,
                    "circuit_breaker_state": breaker.state.value,
                    "error": "Circuit breaker is open.",
                },
            )
            raise LLMCircuitBreakerOpenError("Circuit breaker is open.") from exc

        attempts = route.max_retries + 1
        last_error: LLMProviderError | None = None

        for attempt in range(attempts):
            try:
                response = self._call_with_timeout(provider, request, route.timeout_ms)
            except LLMProviderError as exc:
                last_error = exc
                if attempt < attempts - 1 and route.backoff_ms:
                    time.sleep(route.backoff_ms / 1000.0)
                continue

            self._cost_store.record(request, response)
            breaker.record_success()
            self._complete_event(
                started_event=started_event,
                response=response,
                route_provider=route.provider,
                status=TraceEventStatus.SUCCEEDED,
                attempts=attempt + 1,
            )
            return response

        breaker.record_failure()
        self._trace_event_recorder.complete(
            started_event,
            status=TraceEventStatus.DEGRADED,
            metadata={
                "provider": route.provider,
                "model": route.model_name,
                "task_type": request.task_type,
                "attempts": attempts,
                "circuit_breaker_state": breaker.state.value,
                "error": "Provider call failed safely.",
            },
        )
        raise last_error or LLMProviderError("Provider call failed safely.")

    def _call_with_timeout(
        self,
        provider: LLMProvider,
        request: LLMRequest,
        timeout_ms: int,
    ) -> LLMResponse:
        route = self._router.route_for(request.task_type)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(provider.complete, request, route)
        try:
            return future.result(timeout=timeout_ms / 1000.0)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise LLMTimeoutError("Provider call timed out safely.") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _complete_event(
        self,
        *,
        started_event: TraceEvent,
        response: LLMResponse,
        route_provider: str,
        status: TraceEventStatus,
        attempts: int,
    ) -> None:
        self._trace_event_recorder.complete(
            started_event,
            status=status,
            metadata={
                "provider": response.provider or route_provider,
                "model": response.model_name,
                "latency_ms": response.latency_ms,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "total_tokens": response.total_tokens,
                "estimated_cost": response.estimated_cost,
                "finish_reason": response.finish_reason,
                "attempts": attempts,
            },
        )
