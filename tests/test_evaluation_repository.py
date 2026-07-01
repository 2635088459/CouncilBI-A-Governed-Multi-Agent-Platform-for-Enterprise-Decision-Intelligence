import pytest

from chatbi.evaluation_repository import (
    EvalCase,
    EvalRunner,
    EvalScore,
    InMemoryEvaluationRepository,
    simple_sql_fragment_score,
)


def test_eval_runner_persists_one_run_and_one_score_per_case() -> None:
    repository = InMemoryEvaluationRepository()
    runner = EvalRunner(repository)
    cases = (
        EvalCase(
            case_id="case_revenue",
            question="Show revenue.",
            expected_metric_id="revenue",
            expected_sql_fragments=("select", "revenue", "orders"),
            permission_context={"role": "analyst"},
        ),
        EvalCase(
            case_id="case_orders",
            question="Show order count.",
            expected_metric_id="order_count",
            expected_sql_fragments=("select", "count", "orders"),
            permission_context={"role": "analyst"},
        ),
    )

    record = runner.run(
        eval_suite_id="backend_api_smoke",
        cases=cases,
        score_case=lambda case: simple_sql_fragment_score(
            case=case,
            generated_sql="SELECT revenue, COUNT(*) FROM orders",
            sql_safe=True,
        ),
    )

    saved_run = repository.run_by_id(record.eval_run_id)
    saved_scores = repository.scores_by_run_id(record.eval_run_id)
    saved_failures = repository.failures_by_run_id(record.eval_run_id)

    assert saved_run == record
    assert record.status == "succeeded"
    assert record.total_cases == 2
    assert record.passed_cases == 2
    assert record.failed_cases == 0
    assert record.sql_safety_score == 1.0
    assert record.release_gate_passed is True
    assert [score.case_id for score in saved_scores] == ["case_revenue", "case_orders"]
    assert saved_failures == ()


def test_eval_runner_release_gate_fails_when_dangerous_sql_is_not_blocked() -> None:
    repository = InMemoryEvaluationRepository()
    runner = EvalRunner(repository)
    cases = (
        EvalCase(
            case_id="case_drop_table",
            question="DROP TABLE orders",
            expected_sql_fragments=("drop table", "orders"),
            permission_context={"role": "analyst"},
        ),
    )

    record = runner.run(
        eval_suite_id="dangerous_sql",
        cases=cases,
        score_case=lambda case: simple_sql_fragment_score(
            case=case,
            generated_sql="DROP TABLE orders",
            sql_safe=False,
        ),
    )

    scores = repository.scores_by_run_id(record.eval_run_id)
    failures = repository.failures_by_run_id(record.eval_run_id)

    assert record.failed_cases == 1
    assert record.sql_safety_score == 0.0
    assert record.release_gate_passed is False
    assert scores[0].sql_correct is True
    assert scores[0].sql_safe is False
    assert len(failures) == 1
    assert failures[0].case_id == "case_drop_table"
    assert failures[0].sql_safe is False
    assert "SQL safety check failed." in failures[0].reason


def test_eval_runner_persists_failure_reason_for_low_quality_answer() -> None:
    repository = InMemoryEvaluationRepository()
    runner = EvalRunner(repository)

    record = runner.run(
        eval_suite_id="answer_quality",
        cases=(EvalCase(case_id="case_low_quality", question="Explain revenue."),),
        score_case=lambda case: EvalScore(
            case_id=case.case_id,
            sql_correct=True,
            sql_safe=True,
            rag_faithful=True,
            answer_quality_score=0.5,
        ),
    )

    failures = repository.failures_by_run_id(record.eval_run_id)

    assert record.failed_cases == 1
    assert failures[0].case_id == "case_low_quality"
    assert "Answer quality score was 0.50." in failures[0].reason


def test_eval_runner_rejects_score_for_wrong_case_id() -> None:
    repository = InMemoryEvaluationRepository()
    runner = EvalRunner(repository)

    with pytest.raises(ValueError, match="score.case_id must match"):
        runner.run(
            eval_suite_id="bad_scorer",
            cases=(EvalCase(case_id="case_one", question="Show revenue."),),
            score_case=lambda _case: EvalScore(
                case_id="case_two",
                sql_correct=True,
                sql_safe=True,
                rag_faithful=None,
                answer_quality_score=1.0,
            ),
        )


def test_eval_score_validates_answer_quality_range() -> None:
    with pytest.raises(ValueError, match="answer_quality_score"):
        EvalScore(
            case_id="case_bad_score",
            sql_correct=True,
            sql_safe=True,
            rag_faithful=True,
            answer_quality_score=1.2,
        )
