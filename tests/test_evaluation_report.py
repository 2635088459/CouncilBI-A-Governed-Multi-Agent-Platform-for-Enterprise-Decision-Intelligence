from chatbi.evaluation_report import eval_run_report, require_eval_run_report
from chatbi.evaluation_repository import EvalCase, EvalRunner, InMemoryEvaluationRepository, simple_sql_fragment_score


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
