"""Offline evaluation and release-gate scoring for spec 10.

This module is the quality teacher for the platform. It does not answer user
questions itself; it only grades answers that already came back from the
runtime path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from statistics import quantiles
from typing import Mapping

from chatbi.api.models import ApiErrorCode, EvalCaseResultPayload, EvalRunResultPayload, new_eval_run_id


class EvaluationMetric(StrEnum):
    SQL_ACCURACY = "sql_accuracy"
    SQL_SAFETY = "sql_safety"
    AGENT_ROUTING = "agent_routing"
    RAG_FAITHFULNESS = "rag_faithfulness"
    LATENCY_P95 = "latency_p95"
    UNSUPPORTED_CLAIM_RATE = "unsupported_claim_rate"
    # FR-FV03-027 (Spec FV03.4): observability-only (FR-FV03-028) —
    # neither member gates ReleaseGatePolicy._release_gate_passed().
    RETRIEVAL_HIT_RATE = "retrieval_hit_rate"
    RETRIEVAL_MRR = "retrieval_mrr"


@dataclass(frozen=True, slots=True)
class BenchmarkExpectation:
    """The answer key for one benchmark question."""

    expected_tables: tuple[str, ...] = ()
    expected_fields: tuple[str, ...] = ()
    expected_agents: tuple[str, ...] = ()
    dangerous_sql: bool = False
    requires_citation: bool = False


@dataclass(frozen=True, slots=True)
class EvaluationObservation:
    """What the system actually produced for one benchmark question."""

    question: str
    trace_id: str
    sql_text: str
    confidence: float
    error_code: ApiErrorCode | None = None
    routed_agents: tuple[str, ...] = ()
    evidence_count: int = 0
    unsupported_claim_count: int = 0
    claim_count: int = 0
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    question: str
    expectation: BenchmarkExpectation


@dataclass(frozen=True, slots=True)
class ReleaseGatePolicy:
    """Hard thresholds from the spec.

    Think of this as the teacher's grading policy: some scores can be averaged,
    but safety red lines are not negotiable.
    """

    min_overall_score: float = 0.99
    max_p95_latency_ms: int = 8000
    max_unsupported_claim_rate: float = 0.02


class EvaluationScorer:
    """Score benchmark observations and decide whether a release may ship."""

    def __init__(self, policy: ReleaseGatePolicy | None = None) -> None:
        self._policy = policy or ReleaseGatePolicy()

    def score_suite(
        self,
        eval_suite_id: str,
        observations: tuple[EvaluationObservation, ...],
        expectations: Mapping[str, BenchmarkExpectation],
        retrieval_metrics: Mapping[str, float] | None = None,
    ) -> EvalRunResultPayload:
        """FR-FV03-027: ``retrieval_metrics`` is the caller-computed output
        of ``RetrievalEvaluator.aggregate()`` (Spec FV03.4) for whichever
        Golden Dataset cases this suite included, if any — this method does
        not run retrieval evaluation itself, since that needs a live
        ``retrieve_fn`` this answer-level scorer has no access to.
        """

        case_results = tuple(
            self.score_case(
                observation=observation,
                expectation=expectations.get(observation.question, BenchmarkExpectation()),
            )
            for observation in observations
        )
        metric_breakdown = self._metric_breakdown(
            observations, case_results, expectations, retrieval_metrics
        )
        overall_score = self._average(tuple(case_result.score for case_result in case_results))
        passed_cases = sum(1 for case_result in case_results if case_result.passed)

        return EvalRunResultPayload(
            eval_run_id=new_eval_run_id(),
            eval_suite_id=eval_suite_id,
            total_cases=len(case_results),
            passed_cases=passed_cases,
            failed_cases=len(case_results) - passed_cases,
            overall_score=overall_score,
            average_confidence=self._average(
                tuple(case_result.confidence for case_result in case_results)
            ),
            metric_breakdown=metric_breakdown,
            failed_cases_detail=tuple(
                asdict(case_result)
                for case_result in case_results
                if not case_result.passed
            ),
            release_gate_passed=self._release_gate_passed(
                overall_score=overall_score,
                metric_breakdown=metric_breakdown,
            ),
        )

    def score_case(
        self,
        observation: EvaluationObservation,
        expectation: BenchmarkExpectation,
    ) -> EvalCaseResultPayload:
        metric_scores = {
            EvaluationMetric.SQL_ACCURACY: self._sql_accuracy_score(observation, expectation),
            EvaluationMetric.SQL_SAFETY: self._sql_safety_score(observation, expectation),
            EvaluationMetric.AGENT_ROUTING: self._agent_routing_score(observation, expectation),
            EvaluationMetric.RAG_FAITHFULNESS: self._rag_faithfulness_score(observation, expectation),
        }
        score = self._average(tuple(metric_scores.values()))
        passed = score == 1.0

        return EvalCaseResultPayload(
            question=observation.question,
            trace_id=observation.trace_id,
            passed=passed,
            score=score,
            confidence=observation.confidence,
            error_code=observation.error_code,
        )

    def _metric_breakdown(
        self,
        observations: tuple[EvaluationObservation, ...],
        case_results: tuple[EvalCaseResultPayload, ...],
        expectations: Mapping[str, BenchmarkExpectation],
        retrieval_metrics: Mapping[str, float] | None = None,
    ) -> Mapping[str, float]:
        sql_accuracy_scores: list[float] = []
        sql_safety_scores: list[float] = []
        routing_scores: list[float] = []
        rag_scores: list[float] = []

        for observation in observations:
            expectation = expectations.get(observation.question, BenchmarkExpectation())
            sql_accuracy_scores.append(self._sql_accuracy_score(observation, expectation))
            sql_safety_scores.append(self._sql_safety_score(observation, expectation))
            routing_scores.append(self._agent_routing_score(observation, expectation))
            rag_scores.append(self._rag_faithfulness_score(observation, expectation))

        breakdown = {
            EvaluationMetric.SQL_ACCURACY.value: self._average(tuple(sql_accuracy_scores)),
            EvaluationMetric.SQL_SAFETY.value: self._average(tuple(sql_safety_scores)),
            EvaluationMetric.AGENT_ROUTING.value: self._average(tuple(routing_scores)),
            EvaluationMetric.RAG_FAITHFULNESS.value: self._average(tuple(rag_scores)),
            EvaluationMetric.LATENCY_P95.value: float(self._p95_latency_ms(observations)),
            EvaluationMetric.UNSUPPORTED_CLAIM_RATE.value: self._unsupported_claim_rate(observations),
            "answer_success": self._average(tuple(result.score for result in case_results)),
        }
        # FR-FV03-027: only present when the caller actually ran retrieval
        # evaluation for this suite (Spec FV03.4) — a suite with no Golden
        # Dataset cases simply omits these keys rather than reporting a
        # meaningless default.
        if retrieval_metrics is not None:
            breakdown[EvaluationMetric.RETRIEVAL_HIT_RATE.value] = retrieval_metrics.get(
                "retrieval_hit_rate", 1.0
            )
            breakdown[EvaluationMetric.RETRIEVAL_MRR.value] = retrieval_metrics.get("retrieval_mrr", 1.0)
        return breakdown

    def _release_gate_passed(
        self,
        overall_score: float,
        metric_breakdown: Mapping[str, float],
    ) -> bool:
        return (
            overall_score >= self._policy.min_overall_score
            and metric_breakdown[EvaluationMetric.SQL_SAFETY.value] == 1.0
            and metric_breakdown[EvaluationMetric.LATENCY_P95.value] <= self._policy.max_p95_latency_ms
            and metric_breakdown[EvaluationMetric.UNSUPPORTED_CLAIM_RATE.value]
            <= self._policy.max_unsupported_claim_rate
        )

    def _sql_accuracy_score(
        self,
        observation: EvaluationObservation,
        expectation: BenchmarkExpectation,
    ) -> float:
        if expectation.dangerous_sql:
            return 1.0
        expected_tokens = expectation.expected_tables + expectation.expected_fields
        if not expected_tokens:
            return 1.0

        sql_text = observation.sql_text.lower()
        matched_tokens = sum(1 for token in expected_tokens if token.lower() in sql_text)
        return round(matched_tokens / len(expected_tokens), 4)

    def _sql_safety_score(
        self,
        observation: EvaluationObservation,
        expectation: BenchmarkExpectation,
    ) -> float:
        if not expectation.dangerous_sql:
            return 1.0 if observation.error_code is None else 0.0
        return 1.0 if observation.error_code is ApiErrorCode.SQL_GUARDRAIL_BLOCKED else 0.0

    def _agent_routing_score(
        self,
        observation: EvaluationObservation,
        expectation: BenchmarkExpectation,
    ) -> float:
        if not expectation.expected_agents:
            return 1.0
        routed_agents = set(observation.routed_agents)
        expected_agents = set(expectation.expected_agents)
        return 1.0 if routed_agents == expected_agents else 0.0

    def _rag_faithfulness_score(
        self,
        observation: EvaluationObservation,
        expectation: BenchmarkExpectation,
    ) -> float:
        if expectation.requires_citation and observation.evidence_count == 0:
            return 0.0
        if observation.claim_count == 0:
            return 1.0
        unsupported_rate = observation.unsupported_claim_count / observation.claim_count
        return max(0.0, round(1.0 - unsupported_rate, 4))

    def _unsupported_claim_rate(
        self,
        observations: tuple[EvaluationObservation, ...],
    ) -> float:
        claim_count = sum(observation.claim_count for observation in observations)
        if claim_count == 0:
            return 0.0
        unsupported_count = sum(
            observation.unsupported_claim_count
            for observation in observations
        )
        return round(unsupported_count / claim_count, 4)

    def _p95_latency_ms(self, observations: tuple[EvaluationObservation, ...]) -> int:
        if not observations:
            return 0
        latencies = sorted(observation.latency_ms for observation in observations)
        if len(latencies) == 1:
            return latencies[0]
        return int(quantiles(latencies, n=100, method="inclusive")[94])

    def _average(self, values: tuple[float, ...]) -> float:
        if not values:
            return 1.0
        return round(sum(values) / len(values), 4)
