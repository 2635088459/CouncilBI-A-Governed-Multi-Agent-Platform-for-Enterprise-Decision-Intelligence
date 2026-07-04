from chatbi.core.contracts import ErrorCode
from chatbi.llm import LLMGateway, MockLLMProvider, ModelRoute, ModelRouter
from chatbi.summarization import SafeSummaryGenerator


def test_safe_summary_generator_uses_llm_when_available() -> None:
    route = ModelRoute(
        task_type="answer_summary",
        provider="mock",
        model_name="mock-summary",
        timeout_ms=1000,
    )
    generator = SafeSummaryGenerator(
        LLMGateway(
            providers={"mock": MockLLMProvider()},
            router=ModelRouter(routes={"answer_summary": route}),
        )
    )

    result = generator.summarize(
        answer_text="Revenue increased because enterprise expansion improved retention.",
        user_id="u_001",
        org_id="org_001",
        trace_id="trc_summary_success",
    )

    assert result.summary_text == "mock:answer_summary:answer_summary.v1"
    assert result.degraded is False
    assert result.warning is None
    assert result.provider == "mock"
    assert result.model_name == "mock-summary"


def test_safe_summary_generator_degrades_to_sanitized_fallback_on_provider_failure() -> None:
    route = ModelRoute(
        task_type="answer_summary",
        provider="mock",
        model_name="mock-summary",
        timeout_ms=1000,
        max_retries=0,
    )
    generator = SafeSummaryGenerator(
        LLMGateway(
            providers={"mock": MockLLMProvider(fail_tasks=("answer_summary",))},
            router=ModelRouter(routes={"answer_summary": route}),
        ),
        fallback_max_chars=48,
    )

    result = generator.summarize(
        answer_text=(
            "Revenue increased because enterprise expansion improved retention "
            "and seasonal churn decreased."
        ),
        user_id="u_001",
        org_id="org_001",
        trace_id="trc_summary_degraded",
    )

    assert result.summary_text == "Revenue increased because enterprise..."
    assert result.degraded is True
    assert result.provider is None
    assert result.model_name is None
    assert result.warning is not None
    assert result.warning.code is ErrorCode.LLM_PROVIDER_FAILURE
    assert "Provider failed safely" in result.warning.message
