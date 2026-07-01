"""Local evaluation-runner benchmark helpers for spec 10."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from chatbi.evaluation_repository import (
    EvalCase,
    EvalRunner,
    InMemoryEvaluationRepository,
    simple_sql_fragment_score,
)


@dataclass(frozen=True, slots=True)
class EvaluationRunnerBenchmarkResult:
    case_count: int
    elapsed_ms: float
    eval_run_id: str
    saved_score_count: int
    release_gate_passed: bool

    @property
    def meets_local_runtime_target(self) -> bool:
        return self.elapsed_ms <= 60_000.0


def build_mock_eval_cases(case_count: int = 50) -> tuple[EvalCase, ...]:
    if case_count < 1:
        raise ValueError("case_count must be greater than or equal to 1")

    return tuple(
        EvalCase(
            case_id=f"case_benchmark_{index:03d}",
            question=f"Show revenue benchmark case {index}.",
            expected_metric_id="revenue",
            expected_sql_fragments=("select", "revenue", "orders"),
            permission_context={"role": "analyst", "fixture": "benchmark"},
        )
        for index in range(1, case_count + 1)
    )


def run_evaluation_runner_benchmark(
    case_count: int = 50,
) -> EvaluationRunnerBenchmarkResult:
    repository = InMemoryEvaluationRepository()
    runner = EvalRunner(repository)
    cases = build_mock_eval_cases(case_count)

    started_at = perf_counter()
    record = runner.run(
        eval_suite_id="evaluation_runner_benchmark",
        cases=cases,
        score_case=lambda case: simple_sql_fragment_score(
            case=case,
            generated_sql="SELECT revenue FROM orders",
            sql_safe=True,
        ),
    )
    elapsed_ms = (perf_counter() - started_at) * 1000

    return EvaluationRunnerBenchmarkResult(
        case_count=case_count,
        elapsed_ms=elapsed_ms,
        eval_run_id=record.eval_run_id,
        saved_score_count=len(repository.scores_by_run_id(record.eval_run_id)),
        release_gate_passed=record.release_gate_passed,
    )
