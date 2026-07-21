"""Dashboard-friendly evaluation reports for spec 10.

The runner writes normalized rows: one run, many scores, many failures. This
module turns those rows into a read model that humans and dashboards can render
without knowing repository internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from chatbi.evaluation_repository import (
    EvalFailureRecord,
    EvalRunRecord,
    EvalScore,
    EvaluationRepository,
)


@dataclass(frozen=True, slots=True)
class EvalFailureSummary:
    case_id: str
    reason: str
    sql_correct: bool
    sql_safe: bool
    rag_faithful: bool | None
    answer_quality_score: float


@dataclass(frozen=True, slots=True)
class EvalRunReport:
    eval_run_id: str
    eval_suite_id: str
    org_id: str
    status: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    overall_score: float
    metric_breakdown: Mapping[str, float]
    failed_cases_detail: tuple[EvalFailureSummary, ...]
    release_gate_passed: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "eval_run_id": self.eval_run_id,
            "eval_suite_id": self.eval_suite_id,
            "org_id": self.org_id,
            "status": self.status,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "overall_score": self.overall_score,
            "metric_breakdown": dict(self.metric_breakdown),
            "failed_cases_detail": tuple(
                {
                    "case_id": failure.case_id,
                    "reason": failure.reason,
                    "sql_correct": failure.sql_correct,
                    "sql_safe": failure.sql_safe,
                    "rag_faithful": failure.rag_faithful,
                    "answer_quality_score": failure.answer_quality_score,
                }
                for failure in self.failed_cases_detail
            ),
            "release_gate_passed": self.release_gate_passed,
        }


def eval_run_report(
    repository: EvaluationRepository,
    eval_run_id: str,
    org_id: str | None = None,
) -> EvalRunReport | None:
    """Build a report for one saved eval run."""

    run = repository.run_by_id(eval_run_id, org_id=org_id)
    if run is None:
        return None
    return _report_from_rows(
        run=run,
        scores=repository.scores_by_run_id(eval_run_id),
        failures=repository.failures_by_run_id(eval_run_id),
    )


def require_eval_run_report(
    repository: EvaluationRepository,
    eval_run_id: str,
    org_id: str | None = None,
) -> EvalRunReport:
    report = eval_run_report(repository, eval_run_id, org_id=org_id)
    if report is None:
        raise KeyError(f"eval_run_id was not found: {eval_run_id}")
    return report


def _report_from_rows(
    run: EvalRunRecord,
    scores: tuple[EvalScore, ...],
    failures: tuple[EvalFailureRecord, ...],
) -> EvalRunReport:
    return EvalRunReport(
        eval_run_id=run.eval_run_id,
        eval_suite_id=run.eval_suite_id,
        org_id=run.org_id,
        status=run.status.value,
        total_cases=run.total_cases,
        passed_cases=run.passed_cases,
        failed_cases=run.failed_cases,
        overall_score=_overall_score(run),
        metric_breakdown=_metric_breakdown(scores=scores, sql_safety_score=run.sql_safety_score),
        failed_cases_detail=tuple(_failure_summary(failure) for failure in failures),
        release_gate_passed=run.release_gate_passed,
    )


def _overall_score(run: EvalRunRecord) -> float:
    if run.total_cases == 0:
        return 1.0
    return round(run.passed_cases / run.total_cases, 4)


def _metric_breakdown(
    scores: tuple[EvalScore, ...],
    sql_safety_score: float,
) -> Mapping[str, float]:
    breakdown = {
        "sql_correct": _bool_score(tuple(score.sql_correct for score in scores)),
        "sql_safety": sql_safety_score,
        "rag_faithfulness": _optional_bool_score(
            tuple(score.rag_faithful for score in scores if score.rag_faithful is not None)
        ),
        "answer_quality": _average(tuple(score.answer_quality_score for score in scores)),
    }
    # Code-review fix (Spec FV03.4 gap): retrieval_hit_rate/retrieval_mrr
    # now survive persist-then-reload, the same "None means not scored"
    # convention rag_faithfulness already uses above — only present when
    # at least one persisted score actually carries a retrieval result.
    retrieval_hits = tuple(
        score.retrieval_hit_at_3 for score in scores if score.retrieval_hit_at_3 is not None
    )
    retrieval_ranks = tuple(
        score.retrieval_reciprocal_rank for score in scores if score.retrieval_reciprocal_rank is not None
    )
    if retrieval_hits or retrieval_ranks:
        breakdown["retrieval_hit_rate"] = _optional_bool_score(retrieval_hits)
        breakdown["retrieval_mrr"] = _average(retrieval_ranks)
    return breakdown


def _failure_summary(failure: EvalFailureRecord) -> EvalFailureSummary:
    return EvalFailureSummary(
        case_id=failure.case_id,
        reason=failure.reason,
        sql_correct=failure.sql_correct,
        sql_safe=failure.sql_safe,
        rag_faithful=failure.rag_faithful,
        answer_quality_score=failure.answer_quality_score,
    )


def _bool_score(values: tuple[bool, ...]) -> float:
    if not values:
        return 1.0
    return round(sum(1 for value in values if value) / len(values), 4)


def _optional_bool_score(values: tuple[bool, ...]) -> float:
    return _bool_score(values)


def _average(values: tuple[float, ...]) -> float:
    if not values:
        return 1.0
    return round(sum(values) / len(values), 4)
