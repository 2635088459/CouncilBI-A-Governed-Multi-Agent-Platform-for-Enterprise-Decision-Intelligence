import os
import time

import pytest

from chatbi.core.contracts import ErrorCode, Locale, QueryRequest, UserRole
from chatbi.core.runtime_config import RuntimeConfig
from chatbi.governance import ReadOnlyQueryResult, ReadOnlyQueryStatus
from chatbi.llm import (
    LLMCircuitBreakerOpenError,
    LLMConfigurationError,
    LLMGateway,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    MockLLMProvider,
    ModelRoute,
    ModelRouter,
    OpenAIChatProvider,
    build_llm_client_from_runtime_config,
)
from chatbi.llm.types import estimate_cost, token_count_from_messages
from chatbi.orchestration.simple_orchestrator import SimpleOrchestrator
from chatbi.resilience import CircuitBreaker, CircuitBreakerState
from chatbi.trace_events import TraceEventRecorder, TraceEventStatus


def make_llm_request(task_type: str = "sql_generation") -> LLMRequest:
    return LLMRequest(
        task_type=task_type,
        prompt_version="sql_generation.v1",
        messages=({"role": "user", "content": "Show revenue trend"},),
        model_policy={"requires_readonly_sql": True},
        temperature=0.0,
        max_tokens=128,
        user_id="u_001",
        org_id="org_001",
        trace_id="trc_llm_gateway_test",
    )


def make_query_request() -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question="Show revenue trend",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


def test_mock_provider_returns_deterministic_output_and_token_counts() -> None:
    route = ModelRoute(
        task_type="sql_generation",
        provider="mock",
        model_name="mock-sql",
        timeout_ms=1000,
        prompt_token_cost_per_1k=0.01,
        completion_token_cost_per_1k=0.02,
    )
    request = make_llm_request()
    provider = MockLLMProvider()

    first = provider.complete(request, route)
    second = provider.complete(request, route)

    assert first == second
    assert first.text == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert first.prompt_tokens == token_count_from_messages(request.messages)
    assert first.total_tokens == first.prompt_tokens + first.completion_tokens
    assert first.estimated_cost == estimate_cost(
        first.prompt_tokens,
        first.completion_tokens,
        route,
    )


def test_mock_answer_synthesis_does_not_answer_unasked_highest_revenue() -> None:
    route = ModelRoute(
        task_type="answer_synthesis",
        provider="mock",
        model_name="mock-answer",
        timeout_ms=1000,
    )
    request = LLMRequest(
        task_type="answer_synthesis",
        prompt_version="answer_synthesis.grounded.v1",
        messages=(
            {
                "role": "system",
                "content": "Answer only from provided rows.",
            },
            {
                "role": "user",
                "content": (
                    '{"question": "Show revenue trend.", '
                    '"table_result": {"rows": [{"month": "2012-12", "revenue": 1625}]}}'
                ),
            },
        ),
        model_policy={"grounded_only": True},
        temperature=0.0,
        max_tokens=128,
        user_id="u_001",
        org_id="org_001",
        trace_id="trc_mock_answer_context",
    )

    response = MockLLMProvider().complete(request, route)

    assert response.text == "Revenue trend is ready."


def test_mock_answer_synthesis_uses_provided_rows_for_requested_year() -> None:
    route = ModelRoute(
        task_type="answer_synthesis",
        provider="mock",
        model_name="mock-answer",
        timeout_ms=1000,
    )
    request = LLMRequest(
        task_type="answer_synthesis",
        prompt_version="answer_synthesis.grounded.v1",
        messages=(
            {
                "role": "user",
                "content": (
                    '{"question": "Which month had the highest revenue in 2011?", '
                    '"table_result": {"rows": ['
                    '{"month": "2011-01", "revenue": 844}, '
                    '{"month": "2011-12", "revenue": 1253}]}}'
                ),
            },
        ),
        model_policy={"grounded_only": True},
        temperature=0.0,
        max_tokens=128,
        user_id="u_001",
        org_id="org_001",
        trace_id="trc_mock_answer_2011",
    )

    response = MockLLMProvider().complete(request, route)

    assert (
        response.text
        == "Highest revenue month was 2011-12 with revenue 1253.0, based on the provided SQL rows."
    )


def test_mock_answer_synthesis_does_not_use_support_evidence_for_revenue_rows() -> None:
    route = ModelRoute(
        task_type="answer_synthesis",
        provider="mock",
        model_name="mock-answer",
        timeout_ms=1000,
    )
    request = LLMRequest(
        task_type="answer_synthesis",
        prompt_version="answer_synthesis.grounded.v1",
        messages=(
            {"role": "system", "content": "Answer only from provided rows."},
            {
                "role": "user",
                "content": (
                    '{"question": "Which month had the highest revenue in 2011? Which support ticket area needs attention?", '
                    '"table_result": {"columns": ["month", "revenue"], "rows": ['
                    '{"month": "2011-01", "revenue": 844}, '
                    '{"month": "2011-12", "revenue": 1253}]}, '
                    '"evidence_list": [{"citation_anchor": "business.support_ticket_summary#2026", '
                    '"snippet": "Support ticket summary evidence."}]}'
                ),
            },
        ),
        model_policy={"grounded_only": True},
        temperature=0.0,
        max_tokens=128,
        user_id="u_001",
        org_id="org_001",
        trace_id="trc_mock_answer_mixed_context",
    )

    response = MockLLMProvider().complete(request, route)

    assert "Highest revenue month was 2011-12" in response.text
    assert "Support ticket volume" not in response.text


def test_mock_answer_synthesis_uses_evidence_for_explanation() -> None:
    route = ModelRoute(
        task_type="answer_synthesis",
        provider="mock",
        model_name="mock-answer",
        timeout_ms=1000,
    )
    request = LLMRequest(
        task_type="answer_synthesis",
        prompt_version="answer_synthesis.grounded.v1",
        messages=(
            {"role": "system", "content": "Answer only from evidence."},
            {
                "role": "user",
                "content": (
                    '{"question": "Explain why revenue changed in H1 2026.", '
                    '"table_result": {"rows": [{"month": "2026-06", "revenue": 1350}]}, '
                    '"evidence_list": [{"citation_anchor": "doc_revenue_release_notes#p1", '
                    '"snippet": "Revenue changes were linked to campaign timing."}]}'
                ),
            },
        ),
        model_policy={"grounded_only": True},
        temperature=0.0,
        max_tokens=128,
        user_id="u_001",
        org_id="org_001",
        trace_id="trc_mock_answer_explain",
    )

    response = MockLLMProvider().complete(request, route)

    assert response.text == (
        "Revenue changed based on evidence from doc_revenue_release_notes#p1: "
        "Revenue changes were linked to campaign timing."
    )


def test_model_router_selects_configured_model_by_task_type() -> None:
    sql_route = ModelRoute(
        task_type="sql_generation",
        provider="mock",
        model_name="mock-sql-strong",
        timeout_ms=750,
    )
    router = ModelRouter(routes={"sql_generation": sql_route})

    assert router.route_for("sql_generation") == sql_route
    assert router.route_for("answer_summary").model_name == "mock-chatbi-small"


def test_missing_api_key_rejects_real_provider_initialization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(LLMConfigurationError):
        OpenAIChatProvider()


def test_openai_provider_empty_base_url_uses_default_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "")

    provider = OpenAIChatProvider()

    assert provider._base_url == "https://api.openai.com/v1"


def test_gateway_emits_observability_event_with_provider_model_latency_and_tokens() -> None:
    recorder = TraceEventRecorder(service="llm-gateway")
    route = ModelRoute(
        task_type="sql_generation",
        provider="mock",
        model_name="mock-sql",
        timeout_ms=1000,
    )
    gateway = LLMGateway(
        providers={"mock": MockLLMProvider()},
        router=ModelRouter(routes={"sql_generation": route}),
        trace_event_recorder=recorder,
    )

    response = gateway.complete(make_llm_request())
    events = recorder.store.list_by_trace_id("trc_llm_gateway_test")

    assert response.provider == "mock"
    assert tuple(event.status for event in events) == (
        TraceEventStatus.STARTED,
        TraceEventStatus.SUCCEEDED,
    )
    assert events[-1].metadata["provider"] == "mock"
    assert events[-1].metadata["model"] == "mock-sql"
    assert events[-1].metadata["latency_ms"] == response.latency_ms
    assert events[-1].metadata["total_tokens"] == response.total_tokens


def test_cost_tracking_aggregates_by_user_org_task_and_day() -> None:
    route = ModelRoute(
        task_type="sql_generation",
        provider="mock",
        model_name="mock-sql",
        timeout_ms=1000,
        prompt_token_cost_per_1k=0.01,
        completion_token_cost_per_1k=0.02,
    )
    gateway = LLMGateway(
        providers={"mock": MockLLMProvider()},
        router=ModelRouter(routes={"sql_generation": route}),
    )

    first = gateway.complete(make_llm_request())
    second = gateway.complete(make_llm_request())
    aggregate = gateway.cost_store.aggregate(
        user_id="u_001",
        org_id="org_001",
        task_type="sql_generation",
    )

    assert aggregate.total_tokens == first.total_tokens + second.total_tokens
    assert aggregate.estimated_cost == round(first.estimated_cost + second.estimated_cost, 8)


def test_orchestrator_uses_llm_client_for_sql_generation() -> None:
    route = ModelRoute(
        task_type="sql_generation",
        provider="mock",
        model_name="mock-sql",
        timeout_ms=1000,
    )
    gateway = LLMGateway(
        providers={"mock": MockLLMProvider()},
        router=ModelRouter(routes={"sql_generation": route}),
    )
    orchestrator = SimpleOrchestrator(llm_client=gateway, org_id="org_001")

    answer = orchestrator.answer(make_query_request(), trace_id="trc_orchestrator_llm")

    assert answer.sql_text == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert answer.warnings == ()
    llm_records = gateway.cost_store.list_records()
    assert tuple(record.task_type for record in llm_records) == (
        "sql_generation",
        "answer_synthesis",
    )
    assert all(record.user_id == "u_001" for record in llm_records)
    assert all(record.org_id == "org_001" for record in llm_records)


class SlowProvider:
    provider_name = "slow"

    def complete(self, request: LLMRequest, route: ModelRoute) -> LLMResponse:
        time.sleep(0.05)
        return LLMResponse(
            text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
            model_name=route.model_name,
            provider=self.provider_name,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            estimated_cost=0.0,
            latency_ms=50,
            finish_reason="stop",
        )


class AlwaysFailingProvider:
    provider_name = "failing"

    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, request: LLMRequest, route: ModelRoute) -> LLMResponse:
        self.call_count += 1
        raise LLMProviderError("sanitized provider failure")


class RecordingReadOnlyExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, database_url: str | None, sql_text: str) -> ReadOnlyQueryResult:
        self.calls.append(sql_text)
        return ReadOnlyQueryResult(status=ReadOnlyQueryStatus.SUCCEEDED)


def test_sql_generation_timeout_prevents_sql_execution() -> None:
    route = ModelRoute(
        task_type="sql_generation",
        provider="slow",
        model_name="slow-sql",
        timeout_ms=1,
        max_retries=0,
    )
    gateway = LLMGateway(
        providers={"slow": SlowProvider()},
        router=ModelRouter(routes={"sql_generation": route}),
    )
    readonly_executor = RecordingReadOnlyExecutor()
    orchestrator = SimpleOrchestrator(
        llm_client=gateway,
        readonly_query_executor=readonly_executor,
    )

    answer = orchestrator.answer(make_query_request(), trace_id="trc_llm_timeout")

    assert readonly_executor.calls == []
    assert answer.warnings[0].code is ErrorCode.LLM_PROVIDER_TIMEOUT
    assert "timed out" in answer.answer_text


def test_provider_failure_is_sanitized_before_returning_to_user() -> None:
    route = ModelRoute(
        task_type="sql_generation",
        provider="mock",
        model_name="mock-sql",
        timeout_ms=1000,
        max_retries=0,
    )
    gateway = LLMGateway(
        providers={"mock": MockLLMProvider(fail_tasks=("sql_generation",))},
        router=ModelRouter(routes={"sql_generation": route}),
    )

    with pytest.raises(LLMProviderError, match="Provider call failed safely"):
        gateway.complete(make_llm_request())


def test_repeated_provider_failures_open_circuit_breaker_and_skip_provider_calls() -> None:
    provider = AlwaysFailingProvider()
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60.0)
    route = ModelRoute(
        task_type="sql_generation",
        provider="failing",
        model_name="failing-sql",
        timeout_ms=1000,
        max_retries=0,
    )
    gateway = LLMGateway(
        providers={"failing": provider},
        router=ModelRouter(routes={"sql_generation": route}),
        circuit_breakers={"failing": breaker},
    )

    with pytest.raises(LLMProviderError):
        gateway.complete(make_llm_request())
    with pytest.raises(LLMProviderError):
        gateway.complete(make_llm_request())
    with pytest.raises(LLMCircuitBreakerOpenError):
        gateway.complete(make_llm_request())

    assert provider.call_count == 2
    assert breaker.state is CircuitBreakerState.OPEN


def test_runtime_config_builds_mock_llm_gateway_by_default() -> None:
    gateway = build_llm_client_from_runtime_config(RuntimeConfig())

    response = gateway.complete(make_llm_request())

    assert response.provider == "mock"
    assert response.text == "SELECT month, revenue FROM revenue_by_month LIMIT 100"


def test_runtime_config_rejects_unsupported_llm_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        build_llm_client_from_runtime_config(RuntimeConfig(llm_provider="unknown"))


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY is required for optional real provider smoke test.",
)
def test_optional_openai_smoke_runs_only_when_provider_key_is_present() -> None:
    provider = OpenAIChatProvider()
    route = ModelRoute(
        task_type="answer_summary",
        provider="openai",
        model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        timeout_ms=5000,
        max_retries=0,
    )
    request = make_llm_request(task_type="answer_summary")

    response = provider.complete(request, route)

    assert response.provider == "openai"
    assert response.model_name
