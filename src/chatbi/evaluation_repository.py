"""Evaluation run persistence for spec 10.

This file is intentionally small and boring: it gives the evaluation system a
place to save one run row and one score row per case. Production can replace
the in-memory repository with PostgreSQL later without changing the runner
contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from chatbi.api.models import new_eval_run_id
from chatbi.core.contracts import utc_now


def _empty_permission_context() -> Mapping[str, object]:
    return {}


def _empty_runs() -> dict[str, "EvalRunRecord"]:
    return {}


def _empty_scores() -> dict[str, tuple["EvalScore", ...]]:
    return {}


def _empty_failures() -> dict[str, tuple["EvalFailureRecord", ...]]:
    return {}


class EvalRunStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EvalCase:
    """The answer key input for one evaluation question."""

    case_id: str
    question: str
    expected_metric_id: str | None = None
    expected_sql_fragments: tuple[str, ...] = ()
    permission_context: Mapping[str, object] = field(default_factory=_empty_permission_context)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id is required")
        if not self.question.strip():
            raise ValueError("question is required")


@dataclass(frozen=True, slots=True)
class EvalScore:
    """The stored score for one evaluation case."""

    case_id: str
    sql_correct: bool
    sql_safe: bool
    rag_faithful: bool | None
    answer_quality_score: float

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id is required")
        if not 0.0 <= self.answer_quality_score <= 1.0:
            raise ValueError("answer_quality_score must be between 0.0 and 1.0")

    @property
    def passed(self) -> bool:
        rag_passed = True if self.rag_faithful is None else self.rag_faithful
        return (
            self.sql_correct
            and self.sql_safe
            and rag_passed
            and self.answer_quality_score == 1.0
        )


@dataclass(frozen=True, slots=True)
class EvalFailureRecord:
    """The stored explanation for one failed evaluation case."""

    case_id: str
    reason: str
    sql_correct: bool
    sql_safe: bool
    rag_faithful: bool | None
    answer_quality_score: float

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id is required")
        if not self.reason.strip():
            raise ValueError("reason is required")
        if not 0.0 <= self.answer_quality_score <= 1.0:
            raise ValueError("answer_quality_score must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class EvalRunRecord:
    """The summary row for one eval execution."""

    eval_run_id: str
    eval_suite_id: str
    status: EvalRunStatus
    started_at: datetime
    finished_at: datetime | None
    total_cases: int
    passed_cases: int
    failed_cases: int
    sql_safety_score: float
    release_gate_passed: bool
    org_id: str = "org_legacy"


class EvaluationRepository(Protocol):
    def save_run(self, record: EvalRunRecord) -> None:
        """Insert or replace one eval run row."""
        ...

    def save_score(self, eval_run_id: str, score: EvalScore) -> None:
        """Insert one score row under an eval run."""
        ...

    def save_failure(self, eval_run_id: str, failure: EvalFailureRecord) -> None:
        """Insert one failure row under an eval run."""
        ...

    def run_by_id(self, eval_run_id: str, org_id: str | None = None) -> EvalRunRecord | None:
        """Read one eval run row."""
        ...

    def scores_by_run_id(self, eval_run_id: str) -> tuple[EvalScore, ...]:
        """Read score rows for one eval run."""
        ...

    def failures_by_run_id(self, eval_run_id: str) -> tuple[EvalFailureRecord, ...]:
        """Read failure rows for one eval run."""
        ...


@dataclass(slots=True)
class InMemoryEvaluationRepository(EvaluationRepository):
    """Local implementation shaped like future eval_run and eval_score tables."""

    _runs_by_id: dict[str, EvalRunRecord] = field(default_factory=_empty_runs)
    _scores_by_run_id: dict[str, tuple[EvalScore, ...]] = field(default_factory=_empty_scores)
    _failures_by_run_id: dict[str, tuple[EvalFailureRecord, ...]] = field(default_factory=_empty_failures)

    def save_run(self, record: EvalRunRecord) -> None:
        if not record.eval_run_id.strip():
            raise ValueError("eval_run_id is required")
        self._runs_by_id[record.eval_run_id] = record

    def save_score(self, eval_run_id: str, score: EvalScore) -> None:
        if eval_run_id not in self._runs_by_id:
            raise ValueError("eval_run_id must reference an existing eval run")
        current_scores = self._scores_by_run_id.get(eval_run_id, ())
        self._scores_by_run_id[eval_run_id] = (*current_scores, score)

    def save_failure(self, eval_run_id: str, failure: EvalFailureRecord) -> None:
        if eval_run_id not in self._runs_by_id:
            raise ValueError("eval_run_id must reference an existing eval run")
        current_failures = self._failures_by_run_id.get(eval_run_id, ())
        self._failures_by_run_id[eval_run_id] = (*current_failures, failure)

    def run_by_id(self, eval_run_id: str, org_id: str | None = None) -> EvalRunRecord | None:
        record = self._runs_by_id.get(eval_run_id)
        if record is None:
            return None
        if org_id is not None and record.org_id != org_id:
            return None
        return record

    def scores_by_run_id(self, eval_run_id: str) -> tuple[EvalScore, ...]:
        return self._scores_by_run_id.get(eval_run_id, ())

    def failures_by_run_id(self, eval_run_id: str) -> tuple[EvalFailureRecord, ...]:
        return self._failures_by_run_id.get(eval_run_id, ())

    def latest_run(self, org_id: str | None = None) -> EvalRunRecord | None:
        candidates = tuple(
            record
            for record in self._runs_by_id.values()
            if org_id is None or record.org_id == org_id
        )
        if not candidates:
            return None
        return max(candidates, key=lambda record: record.started_at)


class EvalRunner:
    """Run cases, persist scores, and compute the spec-10 release gate."""

    def __init__(self, repository: EvaluationRepository) -> None:
        self._repository = repository

    def run(
        self,
        eval_suite_id: str,
        cases: tuple[EvalCase, ...],
        score_case: Callable[[EvalCase], EvalScore],
        eval_run_id: str | None = None,
        org_id: str = "org_legacy",
    ) -> EvalRunRecord:
        if not eval_suite_id.strip():
            raise ValueError("eval_suite_id is required")
        if not org_id.strip():
            raise ValueError("org_id is required")

        active_eval_run_id = eval_run_id or new_eval_run_id()
        started_at = utc_now()
        self._repository.save_run(
            EvalRunRecord(
                eval_run_id=active_eval_run_id,
                eval_suite_id=eval_suite_id,
                status=EvalRunStatus.STARTED,
                started_at=started_at,
                finished_at=None,
                total_cases=len(cases),
                passed_cases=0,
                failed_cases=0,
                sql_safety_score=1.0,
                release_gate_passed=False,
                org_id=org_id,
            )
        )

        scores: list[EvalScore] = []
        for case in cases:
            score = score_case(case)
            if score.case_id != case.case_id:
                raise ValueError("score.case_id must match the evaluated case_id")
            self._repository.save_score(active_eval_run_id, score)
            if not score.passed:
                self._repository.save_failure(
                    active_eval_run_id,
                    failure_record_from_score(score),
                )
            scores.append(score)

        final_record = self._final_record(
            eval_run_id=active_eval_run_id,
            eval_suite_id=eval_suite_id,
            started_at=started_at,
            scores=tuple(scores),
            org_id=org_id,
        )
        self._repository.save_run(final_record)
        return final_record

    def _final_record(
        self,
        eval_run_id: str,
        eval_suite_id: str,
        started_at: datetime,
        scores: tuple[EvalScore, ...],
        org_id: str,
    ) -> EvalRunRecord:
        passed_cases = sum(1 for score in scores if score.passed)
        sql_safety_score = _sql_safety_score(scores)
        return EvalRunRecord(
            eval_run_id=eval_run_id,
            eval_suite_id=eval_suite_id,
            status=EvalRunStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=utc_now(),
            total_cases=len(scores),
            passed_cases=passed_cases,
            failed_cases=len(scores) - passed_cases,
            sql_safety_score=sql_safety_score,
            release_gate_passed=sql_safety_score == 1.0 and passed_cases == len(scores),
            org_id=org_id,
        )


def simple_sql_fragment_score(case: EvalCase, generated_sql: str, sql_safe: bool) -> EvalScore:
    """Score one SQL-backed case with deterministic string checks."""

    normalized_sql = generated_sql.lower()
    sql_correct = all(
        fragment.lower() in normalized_sql
        for fragment in case.expected_sql_fragments
    )
    return EvalScore(
        case_id=case.case_id,
        sql_correct=sql_correct,
        sql_safe=sql_safe,
        rag_faithful=None,
        answer_quality_score=1.0 if sql_correct and sql_safe else 0.0,
    )


def failure_record_from_score(score: EvalScore) -> EvalFailureRecord:
    """Turn a failed score into a dashboard-friendly failure row."""

    if score.passed:
        raise ValueError("passed score does not need a failure record")
    return EvalFailureRecord(
        case_id=score.case_id,
        reason=_failure_reason(score),
        sql_correct=score.sql_correct,
        sql_safe=score.sql_safe,
        rag_faithful=score.rag_faithful,
        answer_quality_score=score.answer_quality_score,
    )


def _sql_safety_score(scores: tuple[EvalScore, ...]) -> float:
    if not scores:
        return 1.0
    safe_count = sum(1 for score in scores if score.sql_safe)
    return round(safe_count / len(scores), 4)


def _failure_reason(score: EvalScore) -> str:
    reasons: list[str] = []
    if not score.sql_correct:
        reasons.append("SQL fragments did not match.")
    if not score.sql_safe:
        reasons.append("SQL safety check failed.")
    if score.rag_faithful is False:
        reasons.append("RAG faithfulness check failed.")
    if score.answer_quality_score < 1.0:
        reasons.append(f"Answer quality score was {score.answer_quality_score:.2f}.")
    return " ".join(reasons) or "Evaluation case did not pass."
