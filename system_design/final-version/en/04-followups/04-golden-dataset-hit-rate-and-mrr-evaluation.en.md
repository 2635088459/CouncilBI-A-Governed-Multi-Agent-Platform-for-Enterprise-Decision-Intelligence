# 4.4 A Golden Dataset and Automated Hit Rate / MRR Evaluation for Retrieval

## 1. Problem Solved

Every metric this platform currently gates a release on measures *downstream* answer quality — never retrieval quality in isolation. If retrieval quietly regresses (a bad reranker deploy, a corpus re-ingestion that drops a document, a tokenizer change), nothing in the existing evaluation suite would necessarily catch it before it shows up as a vaguer, harder-to-diagnose drop in `rag_faithfulness`. This document adds retrieval-specific ground truth and metrics — Hit Rate@K and MRR — as a first-class, automated part of the same evaluation system, not a one-off script.

## 2. What Already Exists

- `EvaluationMetric` (`src/chatbi/evaluation.py:18-24`) has six members — `SQL_ACCURACY`, `SQL_SAFETY`, `AGENT_ROUTING`, `RAG_FAITHFULNESS`, `LATENCY_P95`, `UNSUPPORTED_CLAIM_RATE` — none of them retrieval-specific. `RAG_FAITHFULNESS` (`evaluation.py:217-227`) measures whether the *answer's claims* are supported by *whatever evidence retrieval happened to return*; it says nothing about whether retrieval found the *right* evidence in the first place.
- `EvalCase` (`src/chatbi/evaluation_repository.py:44-58`) carries `expected_sql_fragments` for SQL-accuracy grading but has no equivalent field for "which chunk(s) should this question retrieve."
- `rag_benchmark.py:19-105` measures only latency (`p95_latency_ms`, `meets_local_p95_target`); its own module docstring states "This module is not a production metrics system" (`rag_benchmark.py:1-3`) and it runs against `build_mock_rag_service`'s synthetic ~1000-chunk corpus, not real seeded content.
- No occurrence of "hit_rate", "recall", "precision", or "mrr" exists anywhere in `evaluation*.py` (confirmed by repo-wide search) — this is net-new, not a rename or extension of an existing metric.

## 3. Design

### 3.1 Ground truth: extend `EvalCase`

Add one field:

```python
expected_chunk_ids: tuple[str, ...] = ()
```

alongside the existing `expected_sql_fragments` on `EvalCase` (`evaluation_repository.py:44-58`) and the corresponding loader in `evaluation_cases.py:25-35`. A case with an empty tuple is simply not scored for retrieval (mirrors how `expected_sql_fragments` already opts a case in or out of SQL-accuracy scoring today).

### 3.2 The Golden Dataset

Build roughly **50 real business questions** against documents already present in this project's own seed data (`final_seed.py`), each labeled with the `chunk_id`(s) a correct retrieval should surface. This labeling is a **manual/human task**, not something to script — it is also the single largest time cost in this entire four-phase plan. Two ways to make it tractable rather than starting from a blank page:
- Reuse questions already present in `tests/test_rag_agent.py` / `tests/test_knowledge_store.py` as a seed set, since those already exercise real seeded documents with known-correct chunks.
- For genuinely new questions, generate candidates by asking an LLM to write questions *from* a chunk's own text (question generation is a much easier, higher-precision task than question *answering*), then have a human confirm/edit each one and its `chunk_id` label — this is the same "human-in-the-loop over LLM-drafted candidates" pattern the project already documents for other human-acceptance steps (`src/chatbi/human_acceptance.py`), not a new quality-control philosophy for this codebase.

### 3.3 The metrics

New module `retrieval_evaluation.py`, parallel to `evaluation.py`, not folded into it (retrieval evaluation needs the raw ranked chunk-id list per question, a different shape of observation than `EvaluationObservation`'s answer-level fields):

```python
def hit_rate_at_k(retrieved_chunk_ids: tuple[str, ...], expected_chunk_ids: tuple[str, ...], k: int) -> bool:
    return bool(set(retrieved_chunk_ids[:k]) & set(expected_chunk_ids))

def reciprocal_rank(retrieved_chunk_ids: tuple[str, ...], expected_chunk_ids: tuple[str, ...]) -> float:
    for rank, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in expected_chunk_ids:
            return 1.0 / rank
    return 0.0
```

`RetrievalEvaluator.evaluate(cases, retrieve_fn)` runs every case through the live `InMemoryKnowledgeStore.retrieve()` (post-[4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.en.md)/[4.2](02-bm25-keyword-scoring.en.md)/[4.3](03-cross-encoder-reranking.en.md) pipeline, not a mock), and aggregates `hit_rate@3`, `hit_rate@5`, and `mrr` across the suite — the same K values the interview-slide example this plan originated from used, so the eventual before/after numbers are directly comparable to that framing.

### 3.4 Wiring into the release gate

Add `EvaluationMetric.RETRIEVAL_HIT_RATE` and `EvaluationMetric.RETRIEVAL_MRR` to the enum and into `EvaluationScorer._metric_breakdown()`'s returned mapping (`evaluation.py:141-167`), so retrieval quality shows up in the same eval-run report as every other metric, not a separate dashboard nobody checks.

**Decided:** these two metrics start as **observability-only**, not release-gating — `ReleaseGatePolicy` (`evaluation.py:60-70`) gets no new threshold in this phase. Gating on a metric before there is a baseline of what "normal" looks like risks blocking releases on noise. Once a few real evaluation runs establish a stable baseline, a follow-up can add a `min_retrieval_hit_rate` threshold the same way `max_unsupported_claim_rate` already gates today.

## 4. Effort Estimate

Roughly **2.5–3.5 person-days**, and this is the phase whose cost is dominated by human labeling time, not engineering: the `EvalCase` field addition, the new metric module, and the release-gate wiring are each under half a day; hand-labeling ~50 question/chunk-id pairs (even bootstrapped from existing test fixtures and LLM-drafted candidates) realistically takes a full day or more of careful human review to get right, since a wrong label silently corrupts every downstream Hit Rate/MRR number.

## 5. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV03-024 | `EvalCase` must carry an optional `expected_chunk_ids` field for retrieval ground truth. | Proposed |
| FR-FV03-025 | A labeled Golden Dataset of real business questions against real seeded documents must exist, each with one or more expected chunk IDs. | Proposed |
| FR-FV03-026 | The system must compute Hit Rate@K and MRR over the Golden Dataset against the live retrieval pipeline, not a mock. | Proposed |
| FR-FV03-027 | Hit Rate@K and MRR must appear in the same `metric_breakdown` report as the platform's other evaluation metrics. | Proposed |
| FR-FV03-028 | Hit Rate@K and MRR start as observability-only metrics; a numeric release-gate threshold is deferred until a real baseline exists. | Proposed |
