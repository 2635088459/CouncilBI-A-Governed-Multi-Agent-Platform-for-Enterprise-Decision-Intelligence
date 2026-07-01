from chatbi.evaluation_benchmark import (
    build_mock_eval_cases,
    run_evaluation_runner_benchmark,
)


def test_evaluation_benchmark_builds_requested_mock_cases() -> None:
    cases = build_mock_eval_cases(case_count=3)

    assert len(cases) == 3
    assert cases[0].case_id == "case_benchmark_001"
    assert cases[-1].expected_sql_fragments == ("select", "revenue", "orders")


def test_evaluation_runner_benchmark_runs_fifty_cases_under_local_budget() -> None:
    result = run_evaluation_runner_benchmark(case_count=50)

    assert result.case_count == 50
    assert result.eval_run_id.startswith("eval_")
    assert result.saved_score_count == 50
    assert result.release_gate_passed is True
    assert result.elapsed_ms >= 0.0
    assert result.meets_local_runtime_target is True


def test_evaluation_benchmark_rejects_invalid_case_count() -> None:
    try:
        build_mock_eval_cases(case_count=0)
    except ValueError as exc:
        assert "case_count must be greater than or equal to 1" in str(exc)
    else:
        raise AssertionError("Expected invalid case_count to raise ValueError")
