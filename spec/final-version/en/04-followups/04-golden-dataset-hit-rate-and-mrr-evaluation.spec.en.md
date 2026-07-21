# Spec FV03.4: A Golden Dataset and Automated Hit Rate / MRR Evaluation for Retrieval

Source design:
- [4.4 A Golden Dataset and Automated Hit Rate / MRR Evaluation for Retrieval design](../../../../system_design/final-version/en/04-followups/04-golden-dataset-hit-rate-and-mrr-evaluation.en.md)
- [Spec FV03.1](01-unifying-the-vector-and-hybrid-retrieval-paths.spec.en.md) / [Spec FV03.2](02-bm25-keyword-scoring.spec.en.md) / [Spec FV03.3](03-cross-encoder-reranking.spec.en.md) (this spec evaluates the retrieval pipeline those three specs produce; it must be built last, or its numbers describe a pipeline that no longer matches production)
- This spec extends `EvaluationMetric`/`EvaluationScorer` (`src/chatbi/evaluation.py`) in place — there is no separate final-version evaluation spec to supersede; `evaluation.py`'s existing behavior is documented only in code and in `spec/version1/10-evaluation-and-observability.spec.md`/`spec/version2/10-evaluation-and-observability.spec.md`, neither of which is part of the final-version spec set this document belongs to

---

## 1. Purpose

Every metric this platform currently gates a release on measures downstream answer quality or latency — never retrieval quality in isolation. If retrieval quietly regresses, nothing in the existing evaluation suite necessarily catches it before it surfaces as a vaguer, harder-to-diagnose drop in `rag_faithfulness`. This spec adds retrieval-specific ground truth (`expected_chunk_ids`) and metrics (Hit Rate@K, MRR) to the existing evaluation system, as observability-only metrics, wired into the same report as every other metric.

## 2. Scope

**In scope:**
- An `expected_chunk_ids` field on `EvalCase`, and loader support in `evaluation_cases.py`.
- A labeled Golden Dataset of real business questions against documents already present in this project's seed data, each with one or more expected `chunk_id`s.
- A new `retrieval_evaluation.py` module computing Hit Rate@3, Hit Rate@5, and MRR against the live retrieval pipeline (post Specs FV03.1–FV03.3).
- Two new `EvaluationMetric` members (`RETRIEVAL_HIT_RATE`, `RETRIEVAL_MRR`) surfaced in `EvaluationScorer._metric_breakdown()`'s existing report.

**Out of scope:**
- Any release-gate threshold on the new metrics — `ReleaseGatePolicy` gains no new field in this spec (see FR-FV03-028/§9).
- Any change to `rag_faithfulness`, `sql_accuracy`, or any other existing `EvaluationMetric` member's computation.
- Automating the human labeling step itself — that remains a manual review process (§5.2), not a script this spec produces.

## 3. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV03-024 | `EvalCase` MUST carry an optional `expected_chunk_ids: tuple[str, ...] = ()` field. A case with an empty tuple MUST NOT participate in retrieval scoring (mirroring how `expected_sql_fragments` already opts a case in or out of SQL-accuracy scoring). |
| FR-FV03-025 | A labeled Golden Dataset of at least 50 real business questions, each targeting a document already present in this project's seed data (`final_seed.py`), MUST exist, with one or more `expected_chunk_ids` per question. |
| FR-FV03-026 | The system MUST compute Hit Rate@3, Hit Rate@5, and Mean Reciprocal Rank (MRR) for every Golden Dataset case, run against the live `InMemoryKnowledgeStore.retrieve()` pipeline (post Specs FV03.1–FV03.3), not a mock or stub retriever. |
| FR-FV03-027 | `EvaluationScorer._metric_breakdown()`'s returned mapping MUST include `retrieval_hit_rate` and `retrieval_mrr` keys alongside the platform's six existing `EvaluationMetric` values, for any eval run that included Golden Dataset cases. |
| FR-FV03-028 | Hit Rate@K and MRR MUST NOT affect `ReleaseGatePolicy._release_gate_passed()`'s boolean result in this spec — they are observability-only. A numeric release-gate threshold is explicitly deferred to a future spec, once a real baseline exists. |

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV03-011 | Every `expected_chunk_ids` entry in the Golden Dataset MUST reference a `chunk_id` that exists in the project's seeded knowledge store at evaluation time — a dataset entry referencing a nonexistent `chunk_id` MUST fail dataset validation, not silently score as a permanent miss. |
| NFR-FV03-012 | A full retrieval-evaluation run over the ~50-case Golden Dataset MUST complete in under 60 seconds locally, so it is practical to run as part of routine CI rather than only as a manual/offline job. |

## 5. Data Contracts

### 5.1 Ground Truth: `EvalCase` Extension

```python
@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    question: str
    expected_metric_id: str | None = None
    expected_sql_fragments: tuple[str, ...] = ()
    expected_chunk_ids: tuple[str, ...] = ()          # FR-FV03-024
    permission_context: Mapping[str, object] = field(default_factory=_empty_permission_context)
```

`evaluation_cases.py`'s `_eval_case_from_mapping()` gains a corresponding `_string_tuple(raw_case, "expected_chunk_ids", index)` call, reusing the existing string-tuple loader/validator already used for `expected_sql_fragments`.

### 5.2 The Golden Dataset

Roughly 50 question/`expected_chunk_ids` pairs, built by:
- Reusing questions already present in `tests/test_rag_agent.py`/`tests/test_knowledge_store.py`, which already exercise real seeded documents with known-correct chunks, as a seed set.
- For new questions: an LLM drafts a candidate question *from* a chunk's own text (question generation from known-correct source, not answer generation), and a human reviewer confirms or edits both the question and its `chunk_id` label before it enters the dataset — the same human-in-the-loop-over-LLM-drafts pattern this project already documents in `src/chatbi/human_acceptance.py`, not a new quality-control philosophy introduced by this spec.

### 5.3 Retrieval Metrics

```python
def hit_rate_at_k(
    retrieved_chunk_ids: tuple[str, ...],
    expected_chunk_ids: tuple[str, ...],
    k: int,
) -> bool:
    return bool(set(retrieved_chunk_ids[:k]) & set(expected_chunk_ids))


def reciprocal_rank(
    retrieved_chunk_ids: tuple[str, ...],
    expected_chunk_ids: tuple[str, ...],
) -> float:
    for rank, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in expected_chunk_ids:
            return 1.0 / rank
    return 0.0


@dataclass(frozen=True, slots=True)
class RetrievalEvaluationResult:
    case_id: str
    hit_at_3: bool
    hit_at_5: bool
    reciprocal_rank: float


class RetrievalEvaluator:
    def evaluate(
        self,
        cases: tuple[EvalCase, ...],
        retrieve_fn: Callable[[str], tuple[str, ...]],  # question -> ranked chunk_ids
    ) -> tuple[RetrievalEvaluationResult, ...]:
        results: list[RetrievalEvaluationResult] = []
        for case in cases:
            if not case.expected_chunk_ids:
                continue
            retrieved = retrieve_fn(case.question)
            results.append(RetrievalEvaluationResult(
                case_id=case.case_id,
                hit_at_3=hit_rate_at_k(retrieved, case.expected_chunk_ids, 3),
                hit_at_5=hit_rate_at_k(retrieved, case.expected_chunk_ids, 5),
                reciprocal_rank=reciprocal_rank(retrieved, case.expected_chunk_ids),
            ))
        return tuple(results)

    def aggregate(self, results: tuple[RetrievalEvaluationResult, ...]) -> Mapping[str, float]:
        if not results:
            return {"retrieval_hit_rate": 1.0, "retrieval_hit_rate_at_5": 1.0, "retrieval_mrr": 1.0}
        return {
            "retrieval_hit_rate": sum(r.hit_at_3 for r in results) / len(results),
            "retrieval_hit_rate_at_5": sum(r.hit_at_5 for r in results) / len(results),
            "retrieval_mrr": sum(r.reciprocal_rank for r in results) / len(results),
        }
```

### 5.4 `EvaluationMetric` and Scorer Extension

```python
class EvaluationMetric(StrEnum):
    SQL_ACCURACY = "sql_accuracy"
    SQL_SAFETY = "sql_safety"
    AGENT_ROUTING = "agent_routing"
    RAG_FAITHFULNESS = "rag_faithfulness"
    LATENCY_P95 = "latency_p95"
    UNSUPPORTED_CLAIM_RATE = "unsupported_claim_rate"
    RETRIEVAL_HIT_RATE = "retrieval_hit_rate"      # FR-FV03-027
    RETRIEVAL_MRR = "retrieval_mrr"                # FR-FV03-027
```

`EvaluationScorer._metric_breakdown()` gains the two new keys, populated from a `RetrievalEvaluator.aggregate()` call passed in alongside the existing `observations`/`expectations` arguments. `ReleaseGatePolicy` and `_release_gate_passed()` are **not** modified by this spec (FR-FV03-028).

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV03-021 | Loading an eval case mapping with an `expected_chunk_ids` array populates `EvalCase.expected_chunk_ids` correctly; omitting the field defaults to `()`. |
| AC-FV03-022 | The Golden Dataset contains at least 50 cases with non-empty `expected_chunk_ids`, each referencing a `chunk_id` that exists in the project's seeded knowledge store (NFR-FV03-011). |
| AC-FV03-023 | `RetrievalEvaluator.evaluate()` run against the live `InMemoryKnowledgeStore.retrieve()` pipeline produces a result for every case with non-empty `expected_chunk_ids`. |
| AC-FV03-024 | `EvaluationScorer._metric_breakdown()`'s returned mapping includes `retrieval_hit_rate` and `retrieval_mrr` keys alongside the six existing metrics, for any eval run that included Golden Dataset cases. |
| AC-FV03-025 | `EvaluationScorer._release_gate_passed()`'s boolean result is unaffected by `retrieval_hit_rate`/`retrieval_mrr` values — a run with `retrieval_hit_rate == 0.0` still passes the release gate if every other existing gating condition is met. |
| AC-FV03-026 | Running the retrieval evaluation suite twice against an unchanged knowledge store and retrieval pipeline produces identical `hit_at_3`/`hit_at_5`/`reciprocal_rank` values for every case (determinism check). |

## 7. Test Plan

### 7.1 Unit Tests — Ground Truth and Metric Functions

| ID | Layer | Description |
|---|---|---|
| TC-FV03-039 | unit | Loading an `EvalCase` mapping with `expected_chunk_ids` populates the field correctly (AC-FV03-021). |
| TC-FV03-040 | unit | Loading an `EvalCase` mapping without `expected_chunk_ids` defaults to `()` (AC-FV03-021). |
| TC-FV03-041 | unit | `hit_rate_at_k()` returns `True` when any expected chunk id appears within the first `k` retrieved chunk ids, `False` otherwise. |
| TC-FV03-042 | unit | `reciprocal_rank()` returns `1/rank` for the first matching chunk id's 1-indexed position, and `0.0` when no expected chunk id appears anywhere in the retrieved list. |

### 7.2 Unit Tests — `RetrievalEvaluator`

| ID | Layer | Description |
|---|---|---|
| TC-FV03-043 | unit | `RetrievalEvaluator.evaluate()` skips cases with empty `expected_chunk_ids` — `retrieve_fn` is never called for them. |
| TC-FV03-044 | unit | `RetrievalEvaluator.aggregate()` for a fixed set of `RetrievalEvaluationResult`s computes `retrieval_hit_rate`/`retrieval_hit_rate_at_5`/`retrieval_mrr` as the arithmetic mean of the per-case values. |

### 7.3 Integration Tests — Evaluation Pipeline

| ID | Layer | Description |
|---|---|---|
| TC-FV03-045 | integration | `RetrievalEvaluator.evaluate()` run against the live `InMemoryKnowledgeStore.retrieve()` over the Golden Dataset produces a result for every non-empty-`expected_chunk_ids` case, and fails the fixture-loading step if any `expected_chunk_ids` entry references a `chunk_id` absent from the seeded store (AC-FV03-022, AC-FV03-023). |
| TC-FV03-046 | integration | `EvaluationScorer.score_suite()` for a suite that includes Golden Dataset cases returns a `metric_breakdown` containing `retrieval_hit_rate` and `retrieval_mrr` (AC-FV03-024). |
| TC-FV03-047 | integration negative | `EvaluationScorer._release_gate_passed()` returns `True` for a run whose `retrieval_hit_rate == 0.0` when every other existing gating condition passes (AC-FV03-025; confirms FR-FV03-028's observability-only status). |
| TC-FV03-048 | integration | Running the retrieval evaluation suite twice in immediate succession against the same seeded knowledge store produces identical aggregate metrics both times (AC-FV03-026). |

## 8. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV03-024 | AC-FV03-021 | TC-FV03-039, TC-FV03-040 |
| FR-FV03-025 | AC-FV03-022 | TC-FV03-045 |
| FR-FV03-026 | AC-FV03-023 | TC-FV03-041, TC-FV03-042, TC-FV03-043, TC-FV03-045 |
| FR-FV03-027 | AC-FV03-024 | TC-FV03-044, TC-FV03-046 |
| FR-FV03-028 | AC-FV03-025 | TC-FV03-047 |
| NFR-FV03-011 | AC-FV03-022 | TC-FV03-045 |
| NFR-FV03-012 | — | (measured via CI job duration, no dedicated test case; see §9) |

## 9. Implementation Notes

- FR-FV03-025 (the Golden Dataset's existence) has no dedicated "unit test" the way a code requirement would — its acceptance criterion (AC-FV03-022) is a data-quality assertion, checked by the same fixture-loading test (TC-FV03-045) that fails if any `expected_chunk_ids` entry references a `chunk_id` absent from the current seed (NFR-FV03-011). This mirrors how Spec FV10.11 treats fixture-data correctness as something to verify by running it against real code, not by writing a test that only exercises hand-picked values.
- AC-FV03-025/TC-FV03-047 is the test that would catch a regression if someone later adds a `min_retrieval_hit_rate` field to `ReleaseGatePolicy` with a nonzero default without a deliberate follow-up spec deciding to do so — this spec's intent is that no such field exists yet at all (FR-FV03-028), and this test enforces that boundary explicitly rather than leaving it to reviewer attention.
- The ~50-question labeling effort behind AC-FV03-022 is outside this spec's automatable test surface: TC-FV03-045 verifies the dataset's *structural* integrity (every referenced `chunk_id` exists) but cannot verify a human labeled the *correct* `chunk_id` for a given question — that judgment is the manual review process §5.2 already describes, not something a test case can substitute for.
- This spec must be built and evaluated only after Specs FV03.1–FV03.3 land — running it against the pre-FV03.1 pipeline (fake hash-bucket embeddings, Jaccard keyword overlap, no rerank) would produce Hit Rate/MRR numbers describing a retrieval pipeline this platform no longer runs, making any resulting baseline meaningless the moment FV03.1–FV03.3 ship.
