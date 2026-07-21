"""Retrieval-quality evaluation for Spec FV03.4.

Parallel to ``evaluation.py``, not folded into it: retrieval evaluation
needs the raw ranked chunk-id list per question, a different shape of
observation than ``EvaluationObservation``'s answer-level fields. Everything
here is deliberately observability-only (FR-FV03-028) — it does not touch
``ReleaseGatePolicy``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from chatbi.evaluation_repository import EvalCase


def hit_rate_at_k(
    retrieved_chunk_ids: tuple[str, ...],
    expected_chunk_ids: tuple[str, ...],
    k: int,
) -> bool:
    """FR-FV03-026: whether any expected chunk id appears in the top ``k``
    retrieved chunk ids."""

    return bool(set(retrieved_chunk_ids[:k]) & set(expected_chunk_ids))


def reciprocal_rank(
    retrieved_chunk_ids: tuple[str, ...],
    expected_chunk_ids: tuple[str, ...],
) -> float:
    """FR-FV03-026: 1/rank of the first matching chunk id (1-indexed), or
    0.0 if no expected chunk id appears anywhere in the retrieved list."""

    for rank, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in expected_chunk_ids:
            return 1.0 / rank
    return 0.0


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationResult:
    """Per-case retrieval outcome for one Golden Dataset question."""

    case_id: str
    hit_at_3: bool
    hit_at_5: bool
    reciprocal_rank_value: float


class RetrievalEvaluator:
    """FR-FV03-026: runs Golden Dataset cases through the live retrieval
    pipeline and computes Hit Rate@3, Hit Rate@5, and MRR.

    ``retrieve_fn`` takes a question and returns its ranked chunk ids —
    callers wire this to ``InMemoryKnowledgeStore.retrieve()`` (post Specs
    FV03.1–FV03.3), not a mock or stub retriever.
    """

    def evaluate(
        self,
        cases: tuple[EvalCase, ...],
        retrieve_fn: Callable[[str], tuple[str, ...]],
    ) -> tuple[RetrievalEvaluationResult, ...]:
        results: list[RetrievalEvaluationResult] = []
        for case in cases:
            if not case.expected_chunk_ids:
                # FR-FV03-024: an empty expected_chunk_ids opts this case
                # out of retrieval scoring entirely.
                continue
            retrieved = retrieve_fn(case.question)
            results.append(
                RetrievalEvaluationResult(
                    case_id=case.case_id,
                    hit_at_3=hit_rate_at_k(retrieved, case.expected_chunk_ids, 3),
                    hit_at_5=hit_rate_at_k(retrieved, case.expected_chunk_ids, 5),
                    reciprocal_rank_value=reciprocal_rank(retrieved, case.expected_chunk_ids),
                )
            )
        return tuple(results)

    def aggregate(self, results: tuple[RetrievalEvaluationResult, ...]) -> Mapping[str, float]:
        """FR-FV03-027: the two keys this module contributes to
        ``EvaluationScorer``'s ``metric_breakdown`` report. No cases scored
        (e.g. no Golden Dataset cases in this suite) defaults to 1.0,
        matching ``EvaluationScorer._average()``'s existing "nothing to
        grade passes" convention.
        """

        if not results:
            return {
                "retrieval_hit_rate": 1.0,
                "retrieval_hit_rate_at_5": 1.0,
                "retrieval_mrr": 1.0,
            }
        return {
            "retrieval_hit_rate": round(sum(result.hit_at_3 for result in results) / len(results), 4),
            "retrieval_hit_rate_at_5": round(
                sum(result.hit_at_5 for result in results) / len(results), 4
            ),
            "retrieval_mrr": round(
                sum(result.reciprocal_rank_value for result in results) / len(results), 4
            ),
        }
