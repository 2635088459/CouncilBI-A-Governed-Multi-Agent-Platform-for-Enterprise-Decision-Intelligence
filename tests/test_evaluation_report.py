from datetime import datetime, timezone

from chatbi.evaluation_report import eval_run_report, require_eval_run_report
from chatbi.evaluation_repository import (
    EvalCase,
    EvalRunner,
    EvalRunRecord,
    EvalRunStatus,
    EvalScore,
    InMemoryEvaluationRepository,
    simple_sql_fragment_score,
)


def test_eval_run_report_summarizes_scores_and_failures() -> None:
    repository = InMemoryEvaluationRepository()
    record = EvalRunner(repository).run(
        eval_suite_id="report_suite",
        cases=(
            EvalCase(
                case_id="case_revenue",
                question="Show revenue.",
                expected_sql_fragments=("select", "revenue"),
            ),
            EvalCase(
                case_id="case_drop",
                question="DROP TABLE orders",
                expected_sql_fragments=("drop table", "orders"),
            ),
        ),
        score_case=lambda case: simple_sql_fragment_score(
            case=case,
            generated_sql=(
                "SELECT revenue FROM orders"
                if case.case_id == "case_revenue"
                else "DROP TABLE orders"
            ),
            sql_safe=case.case_id != "case_drop",
        ),
    )

    report = require_eval_run_report(repository, record.eval_run_id)
    payload = report.to_payload()

    assert report.eval_run_id == record.eval_run_id
    assert report.eval_suite_id == "report_suite"
    assert report.status == "succeeded"
    assert report.total_cases == 2
    assert report.passed_cases == 1
    assert report.failed_cases == 1
    assert report.overall_score == 0.5
    assert report.metric_breakdown["sql_correct"] == 1.0
    assert report.metric_breakdown["sql_safety"] == 0.5
    assert report.metric_breakdown["answer_quality"] == 0.5
    assert report.release_gate_passed is False
    assert report.failed_cases_detail[0].case_id == "case_drop"
    assert "SQL safety check failed." in report.failed_cases_detail[0].reason
    assert payload["failed_cases_detail"][0]["case_id"] == "case_drop"


def test_eval_run_report_persists_retrieval_hit_rate_and_mrr() -> None:
    # Code-review regression test (Spec FV03.4 gap): retrieval_hit_rate/
    # retrieval_mrr must survive a persist-then-reload round trip through
    # the eval repository, not just exist in the in-memory
    # EvalRunResultPayload of a single score_suite() call.
    repository = InMemoryEvaluationRepository()
    repository.save_run(
        EvalRunRecord(
            eval_run_id="eval_retrieval",
            eval_suite_id="retrieval_suite",
            status=EvalRunStatus.SUCCEEDED,
            started_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            finished_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            total_cases=2,
            passed_cases=2,
            failed_cases=0,
            sql_safety_score=1.0,
            release_gate_passed=True,
        )
    )
    repository.save_score(
        "eval_retrieval",
        EvalScore(
            case_id="case_hit",
            sql_correct=True,
            sql_safe=True,
            rag_faithful=None,
            answer_quality_score=1.0,
            retrieval_hit_at_3=True,
            retrieval_reciprocal_rank=1.0,
        ),
    )
    repository.save_score(
        "eval_retrieval",
        EvalScore(
            case_id="case_miss",
            sql_correct=True,
            sql_safe=True,
            rag_faithful=None,
            answer_quality_score=1.0,
            retrieval_hit_at_3=False,
            retrieval_reciprocal_rank=0.0,
        ),
    )

    report = require_eval_run_report(repository, "eval_retrieval")

    assert report.metric_breakdown["retrieval_hit_rate"] == 0.5
    assert report.metric_breakdown["retrieval_mrr"] == 0.5


def test_eval_run_report_omits_retrieval_metrics_when_no_case_has_ground_truth() -> None:
    repository = InMemoryEvaluationRepository()
    record = EvalRunner(repository).run(
        eval_suite_id="no_retrieval_suite",
        cases=(EvalCase(case_id="case_sql", question="Show revenue.", expected_sql_fragments=("revenue",)),),
        score_case=lambda case: simple_sql_fragment_score(
            case=case, generated_sql="SELECT revenue FROM orders", sql_safe=True
        ),
    )

    report = require_eval_run_report(repository, record.eval_run_id)

    assert "retrieval_hit_rate" not in report.metric_breakdown
    assert "retrieval_mrr" not in report.metric_breakdown


def test_eval_run_report_returns_none_for_missing_run() -> None:
    repository = InMemoryEvaluationRepository()

    report = eval_run_report(repository, "eval_missing")

    assert report is None


def test_require_eval_run_report_rejects_missing_run() -> None:
    repository = InMemoryEvaluationRepository()

    try:
        require_eval_run_report(repository, "eval_missing")
    except KeyError as exc:
        assert "eval_missing" in str(exc)
    else:
        raise AssertionError("Expected missing eval run to raise KeyError.")
