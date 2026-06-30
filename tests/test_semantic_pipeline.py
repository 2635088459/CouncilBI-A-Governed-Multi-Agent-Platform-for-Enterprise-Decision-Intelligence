from datetime import date

import pytest

from chatbi.core.contracts import GuardrailDecision, Locale, QueryRequest, UserRole, new_trace_id
from chatbi.semantic.catalog import MetricDefinition, SemanticCatalog
from chatbi.semantic.pipeline import SemanticNl2SqlPipeline, SemanticResolveStatus


def make_request(question: str) -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question=question,
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


def test_semantic_pipeline_hands_generated_sql_to_guardrail() -> None:
    pipeline = SemanticNl2SqlPipeline(today=date(2026, 6, 17))

    result = pipeline.run(
        request=make_request("Show revenue trend."),
        trace_id=new_trace_id(),
    )

    assert result.generated_sql is not None
    assert result.guardrail_result is not None
    assert result.generated_sql.semantic_version == "sem_v1"
    assert result.generated_sql.sql_explanation
    assert result.semantic_resolution.status is SemanticResolveStatus.RESOLVED
    assert result.semantic_resolution.semantic_version_id == "sem_v1"
    assert [metric.metric_id for metric in result.semantic_resolution.metrics] == ["revenue"]
    assert [dimension.dimension_id for dimension in result.semantic_resolution.dimensions] == ["order_date"]
    assert result.semantic_resolution.time_range is not None
    assert result.sql_preview is not None
    assert result.sql_preview.executes is False
    assert result.sql_preview.semantic_version_id == "sem_v1"
    assert result.guardrail_result.decision is GuardrailDecision.ALLOW
    assert result.guardrail_result.safe_sql == result.generated_sql.sql_text


def test_semantic_pipeline_resolves_benchmark_question_deterministically() -> None:
    pipeline = SemanticNl2SqlPipeline(today=date(2026, 6, 17))
    request = make_request("show monthly revenue for 2024")

    fingerprints: list[tuple[tuple[str, ...], tuple[str, ...], str]] = []
    for _ in range(20):
        result = pipeline.run(request=request, trace_id=new_trace_id())

        assert result.sql_preview is not None
        fingerprints.append(
            (
                tuple(metric.metric_id for metric in result.semantic_resolution.metrics),
                tuple(dimension.grain for dimension in result.semantic_resolution.dimensions),
                result.sql_preview.sql_hash,
            )
        )

    assert len(set(fingerprints)) == 1
    assert fingerprints[0][0] == ("revenue",)
    assert fingerprints[0][1] == ("month",)


def test_semantic_pipeline_requires_resolved_metric() -> None:
    pipeline = SemanticNl2SqlPipeline(today=date(2026, 6, 17))

    with pytest.raises(ValueError, match="metric"):
        pipeline.run(
            request=make_request("Show gross margin trend."),
            trace_id=new_trace_id(),
        )


def test_semantic_pipeline_returns_clarification_for_ambiguous_metric() -> None:
    revenue = MetricDefinition(
        name="revenue",
        description="Revenue.",
        table_name="orders",
        sql_expression="SUM(orders.order_amount)",
        semantic_version="sem_v1",
        synonyms=("sales",),
    )
    gross_sales = MetricDefinition(
        name="gross_sales",
        description="Gross sales.",
        table_name="orders",
        sql_expression="SUM(orders.gross_amount)",
        semantic_version="sem_v1",
        synonyms=("sales",),
    )
    pipeline = SemanticNl2SqlPipeline(
        catalog=SemanticCatalog(metrics=(revenue, gross_sales)),
        today=date(2026, 6, 17),
    )

    result = pipeline.run(
        request=make_request("Show sales trend."),
        trace_id=new_trace_id(),
    )

    assert result.parsed_question.needs_clarification
    assert result.semantic_resolution.status is SemanticResolveStatus.NEEDS_CLARIFICATION
    assert [metric.metric_id for metric in result.semantic_resolution.metrics] == ["revenue", "gross_sales"]
    assert result.semantic_resolution.dimensions == []
    assert result.semantic_resolution.time_range is None
    assert result.semantic_resolution.clarification_question == (
        "Please clarify which metric you mean: revenue, gross_sales."
    )
    assert result.generated_sql is None
    assert result.sql_preview is None
    assert result.guardrail_result is None
    assert result.clarification == "Please clarify which metric you mean: revenue, gross_sales."


def test_semantic_pipeline_denies_high_sensitivity_field_before_sql_generation() -> None:
    pipeline = SemanticNl2SqlPipeline(today=date(2026, 6, 17))

    result = pipeline.run(
        request=make_request("Show customer id trend."),
        trace_id=new_trace_id(),
    )

    assert result.parsed_question.requested_field is not None
    assert result.parsed_question.requested_field.name == "user_id"
    assert result.semantic_resolution.status is SemanticResolveStatus.PERMISSION_DENIED
    assert result.semantic_resolution.semantic_version_id == "sem_v1"
    assert result.semantic_resolution.metrics == []
    assert result.semantic_resolution.dimensions == []
    assert result.semantic_resolution.time_range is None
    assert result.generated_sql is None
    assert result.sql_preview is None
    assert result.guardrail_result is not None
    assert result.guardrail_result.decision is GuardrailDecision.DENY
    assert result.guardrail_result.error_code is not None
    assert result.guardrail_result.error_code.value == "SQL_DENY_OBJECT"
    assert result.guardrail_result.message is not None
    assert "high-sensitivity" in result.guardrail_result.message
