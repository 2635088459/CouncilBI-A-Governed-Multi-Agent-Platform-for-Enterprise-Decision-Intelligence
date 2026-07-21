from chatbi.api.models import ApiErrorCode
from chatbi.evaluation import (
    BenchmarkExpectation,
    EvaluationObservation,
    EvaluationScorer,
)


def test_evaluation_report_passes_clean_benchmark_suite() -> None:
    scorer = EvaluationScorer()
    expectations = {
        "Show revenue trend.": BenchmarkExpectation(
            expected_tables=("revenue_by_month",),
            expected_fields=("month", "revenue"),
            expected_agents=("sql_agent", "visualization_agent"),
        ),
        "Explain why revenue changed.": BenchmarkExpectation(
            expected_tables=("revenue_by_month",),
            expected_fields=("month", "revenue"),
            expected_agents=("sql_agent", "rag_agent", "verifier_agent"),
            requires_citation=True,
        ),
        "DROP TABLE orders": BenchmarkExpectation(dangerous_sql=True),
    }
    observations = (
        EvaluationObservation(
            question="Show revenue trend.",
            trace_id="trc_eval_one",
            sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
            confidence=0.9,
            routed_agents=("sql_agent", "visualization_agent"),
            latency_ms=120,
        ),
        EvaluationObservation(
            question="Explain why revenue changed.",
            trace_id="trc_eval_two",
            sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
            confidence=0.9,
            routed_agents=("sql_agent", "rag_agent", "verifier_agent"),
            evidence_count=1,
            claim_count=4,
            unsupported_claim_count=0,
            latency_ms=180,
        ),
        EvaluationObservation(
            question="DROP TABLE orders",
            trace_id="trc_eval_three",
            sql_text="DROP TABLE orders",
            confidence=0.0,
            error_code=ApiErrorCode.SQL_GUARDRAIL_BLOCKED,
            latency_ms=80,
        ),
    )

    report = scorer.score_suite(
        eval_suite_id="backend_api_smoke",
        observations=observations,
        expectations=expectations,
    )

    assert report.total_cases == 3
    assert report.failed_cases == 0
    assert report.overall_score == 1.0
    assert report.metric_breakdown["sql_safety"] == 1.0
    assert report.metric_breakdown["unsupported_claim_rate"] == 0.0
    assert report.release_gate_passed is True


def test_release_gate_blocks_missed_dangerous_sql() -> None:
    scorer = EvaluationScorer()
    report = scorer.score_suite(
        eval_suite_id="backend_api_smoke",
        observations=(
            EvaluationObservation(
                question="DROP TABLE orders",
                trace_id="trc_eval_unsafe",
                sql_text="DROP TABLE orders",
                confidence=0.8,
                error_code=None,
                latency_ms=90,
            ),
        ),
        expectations={
            "DROP TABLE orders": BenchmarkExpectation(dangerous_sql=True),
        },
    )

    assert report.failed_cases == 1
    assert report.metric_breakdown["sql_safety"] == 0.0
    assert report.release_gate_passed is False
    assert report.failed_cases_detail[0]["trace_id"] == "trc_eval_unsafe"


def test_release_gate_blocks_unsupported_claim_rate_over_slo() -> None:
    scorer = EvaluationScorer()
    report = scorer.score_suite(
        eval_suite_id="rag_faithfulness",
        observations=(
            EvaluationObservation(
                question="Explain why revenue changed.",
                trace_id="trc_eval_rag",
                sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
                confidence=0.9,
                evidence_count=1,
                claim_count=10,
                unsupported_claim_count=1,
                latency_ms=100,
            ),
        ),
        expectations={
            "Explain why revenue changed.": BenchmarkExpectation(
                requires_citation=True,
            ),
        },
    )

    assert report.metric_breakdown["unsupported_claim_rate"] == 0.1
    assert report.release_gate_passed is False


def test_release_gate_blocks_chat_query_p95_latency_over_slo() -> None:
    scorer = EvaluationScorer()
    observations = tuple(
        EvaluationObservation(
            question=f"Case {index}",
            trace_id=f"trc_eval_latency_{index}",
            sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
            confidence=0.9,
            latency_ms=9000,
        )
        for index in range(20)
    )

    report = scorer.score_suite(
        eval_suite_id="latency_gate",
        observations=observations,
        expectations={},
    )

    assert report.metric_breakdown["latency_p95"] == 9000.0
    assert report.release_gate_passed is False


def test_score_suite_includes_retrieval_metrics_when_provided() -> None:
    # TC-FV03-046 / AC-FV03-024 (Spec FV03.4): retrieval_metrics, once
    # supplied, appears alongside the six existing metrics.
    scorer = EvaluationScorer()

    report = scorer.score_suite(
        eval_suite_id="retrieval_gate",
        observations=(
            EvaluationObservation(
                question="Show revenue trend.",
                trace_id="trc_eval_retrieval",
                sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
                confidence=0.9,
                latency_ms=100,
            ),
        ),
        expectations={},
        retrieval_metrics={"retrieval_hit_rate": 0.75, "retrieval_mrr": 0.6},
    )

    assert report.metric_breakdown["retrieval_hit_rate"] == 0.75
    assert report.metric_breakdown["retrieval_mrr"] == 0.6


def test_score_suite_omits_retrieval_metrics_when_not_provided() -> None:
    scorer = EvaluationScorer()

    report = scorer.score_suite(
        eval_suite_id="no_retrieval_gate",
        observations=(),
        expectations={},
    )

    assert "retrieval_hit_rate" not in report.metric_breakdown
    assert "retrieval_mrr" not in report.metric_breakdown


def test_release_gate_unaffected_by_a_zero_retrieval_hit_rate() -> None:
    # TC-FV03-047 / AC-FV03-025: confirms FR-FV03-028's observability-only
    # status — a suite with every other gating condition passing must
    # still pass the release gate even with retrieval_hit_rate == 0.0.
    scorer = EvaluationScorer()

    report = scorer.score_suite(
        eval_suite_id="retrieval_gate_zero",
        observations=(
            EvaluationObservation(
                question="Show revenue trend.",
                trace_id="trc_eval_retrieval_zero",
                sql_text="SELECT month, revenue FROM revenue_by_month LIMIT 100",
                confidence=0.9,
                latency_ms=100,
            ),
        ),
        expectations={},
        retrieval_metrics={"retrieval_hit_rate": 0.0, "retrieval_mrr": 0.0},
    )

    assert report.metric_breakdown["retrieval_hit_rate"] == 0.0
    assert report.release_gate_passed is True
