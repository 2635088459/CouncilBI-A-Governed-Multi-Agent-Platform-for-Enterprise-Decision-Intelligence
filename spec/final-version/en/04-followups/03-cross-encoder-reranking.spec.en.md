# Spec FV03.3: Adding a Real Cross-Encoder Rerank Stage

Source design:
- [4.3 Adding a Real Cross-Encoder Rerank Stage design](../../../../system_design/final-version/en/04-followups/03-cross-encoder-reranking.en.md)
- [Spec FV03.1: Unifying the Vector-Only and Hybrid Retrieval Paths, and Wiring in Real Embeddings](01-unifying-the-vector-and-hybrid-retrieval-paths.spec.en.md) / [Spec FV03.2: Replacing Jaccard Keyword Overlap with Real BM25 Scoring](02-bm25-keyword-scoring.spec.en.md) (this spec's rerank stage operates on the candidate ordering those two specs already produce; it does not change either)

---

## 1. Purpose

`InMemoryKnowledgeStore.retrieve()`'s own docstring already claims a four-stage pipeline — `filter -> hybrid retrieval -> rerank -> dedupe -> evidence output` — but no rerank stage exists: what runs after hybrid scoring today is dedupe-and-truncate over the *same* scores computed one step earlier. This spec builds the missing stage: a genuine second-pass re-scoring of a narrowed candidate set with a cross-encoder model, which reads the query and a chunk jointly rather than comparing independently-computed scores after the fact.

## 2. Scope

**In scope:**
- A rerank step inserted between hybrid scoring (Specs FV03.1/FV03.2) and the existing dedupe step, bounded to the narrowed `2 * top_k` candidate window `retrieve()` already carves out.
- A locally-run cross-encoder model (`sentence-transformers`' `CrossEncoder` wrapping `BAAI/bge-reranker-base`), lazily loaded once per process.
- Populating `RetrievalStats.reranked_count` with the true count of candidates that passed through the cross-encoder.
- A fallback to the pre-rerank hybrid ordering when the reranker is unavailable or errors.

**Out of scope:**
- Any change to hybrid scoring itself (Specs FV03.1/FV03.2) or to `_dedupe_adjacent_chunks()`'s own logic.
- Any change to the `RetrievalStats` schema — `reranked_count` already exists (parent Spec FV-03's contracts); this spec only changes what value populates it.
- Calling an external reranking API/service — the model runs in-process, consistent with Spec FV03.1's in-process embedding approach.

## 3. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV03-021 | `retrieve()` MUST re-score the top `2 * top_k` hybrid-ranked candidates with a cross-encoder model, scoring `(question, chunk_text)` pairs directly, before `_dedupe_adjacent_chunks()` and truncation to `top_k` run. |
| FR-FV03-022 | `RetrievalStats.reranked_count` MUST reflect the number of candidates that actually passed through the cross-encoder rerank pass — `min(len(filtered_records), 2 * query.top_k)` when a reranker is configured, `0` when it is not. |
| FR-FV03-023 | If the reranker model fails to load, or raises an exception when scoring a request's candidates, `retrieve()` MUST fall back to the pre-rerank hybrid ordering rather than propagating the exception or failing the request. |

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV03-009 | The cross-encoder model MUST be loaded at most once per process lifetime (a lazy singleton or startup-time load), not reloaded on every request. |
| NFR-FV03-010 | Reranking a candidate set of `2 * top_k` (10 pairs at the default `top_k=5`) MUST add no more than 200ms to P95 request latency on CPU, measured via `rag_benchmark.py`'s existing harness. |

## 5. Data Contracts

### 5.1 `CrossEncoderReranker` and Fallback Logic

```python
class CrossEncoderReranker(Protocol):
    def score(self, pairs: tuple[tuple[str, str], ...]) -> tuple[float, ...]: ...


class BgeCrossEncoderReranker:
    """FR-FV03-021 / NFR-FV03-009: loads BAAI/bge-reranker-base once,
    lazily, at first use — not per request."""

    def __init__(self) -> None:
        self._model: "CrossEncoder | None" = None

    def score(self, pairs: tuple[tuple[str, str], ...]) -> tuple[float, ...]:
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder("BAAI/bge-reranker-base")
        return tuple(float(s) for s in self._model.predict(list(pairs)))


def rerank(
    question: str,
    candidates: tuple[KnowledgeChunkRecord, ...],
    reranker: CrossEncoderReranker | None,
) -> tuple[KnowledgeChunkRecord, ...]:
    """FR-FV03-023: on reranker absence or any error, returns candidates
    unchanged (pre-rerank hybrid ordering) rather than propagating."""
    if reranker is None:
        return candidates
    try:
        pairs = tuple((question, c.chunk.chunk_text) for c in candidates)
        scores = reranker.score(pairs)
    except Exception:
        return candidates
    ranked = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)
    return tuple(record for record, _ in ranked)
```

### 5.2 `retrieve()` Integration

```python
def retrieve(self, query: RetrievalQuery, trace_id: str = "") -> RetrievalResult:
    filtered_records = self.list_chunk_records(...)
    ranked_records = self._rank_records(filtered_records, query)          # Specs FV03.1/FV03.2
    narrowed = ranked_records[: max(query.top_k * 2, query.top_k)]
    reranked = rerank(query.question, narrowed, self._reranker)          # FR-FV03-021
    selected_records = self._dedupe_adjacent_chunks(reranked)
    selected_records = selected_records[: query.top_k]
    evidence_list = tuple(record.to_evidence_item() for record in selected_records)
    return RetrievalResult(
        evidence_list=evidence_list,
        ...,
        retrieval_stats=RetrievalStats(
            candidate_count=len(self._chunks_by_chunk_id),
            filtered_count=len(filtered_records),
            reranked_count=(
                min(len(filtered_records), query.top_k * 2)
                if self._reranker is not None
                else 0
            ),  # FR-FV03-022
            selected_count=len(evidence_list),
            latency_ms=latency_ms,
        ),
    )
```

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV03-017 | For two candidates with near-identical hybrid scores but only one truly answering the question (verified with a fake `CrossEncoderReranker`), the reranked order places the truly-relevant one first, even when its pre-rerank hybrid score was lower. |
| AC-FV03-018 | `RetrievalStats.reranked_count` equals `min(len(filtered_records), 2 * top_k)` when a reranker is configured, and `0` when it is not. |
| AC-FV03-019 | When the reranker raises an exception during scoring, `retrieve()` still returns a non-error result using the pre-rerank hybrid ordering, not a propagated exception. |
| AC-FV03-020 | The cross-encoder model is instantiated at most once across N sequential `retrieve()` calls made against the same `BgeCrossEncoderReranker` instance in the same process. |

## 7. Test Plan

### 7.1 Unit Tests — `rerank()`

| ID | Layer | Description |
|---|---|---|
| TC-FV03-031 | unit | `rerank()` with a fake reranker that scores in reverse order returns candidates in the reversed order (mechanism test for AC-FV03-017). |
| TC-FV03-032 | unit | `rerank()` with `reranker=None` returns candidates unchanged, in original order. |
| TC-FV03-033 | unit | `rerank()` with a fake reranker that raises on `score()` returns candidates unchanged (pre-rerank order), not an exception (AC-FV03-019). |

### 7.2 Unit Tests — `BgeCrossEncoderReranker` Lazy Loading

| ID | Layer | Description |
|---|---|---|
| TC-FV03-034 | unit | Two calls to `score()` on the same `BgeCrossEncoderReranker` instance trigger model construction exactly once (AC-FV03-020, NFR-FV03-009). |

### 7.3 Unit Tests — `retrieve()` Integration

| ID | Layer | Description |
|---|---|---|
| TC-FV03-035 | unit | `retrieve()` with a reranker configured populates `RetrievalStats.reranked_count == min(len(filtered_records), 2 * top_k)` (AC-FV03-018). |
| TC-FV03-036 | unit | `retrieve()` with no reranker configured populates `RetrievalStats.reranked_count == 0`. |
| TC-FV03-037 | unit | `retrieve()` with a fake reranker that ranks a specific chunk highest returns that chunk first in `evidence_list`, even though its pre-rerank hybrid score was lower than another candidate's (AC-FV03-017). |

### 7.4 Integration Test — Real Model

| ID | Layer | Description |
|---|---|---|
| TC-FV03-038 | integration | `POST /api/v2/chat/query` for a RAG-classified question with the real `BgeCrossEncoderReranker` configured completes successfully and returns a non-empty `evidence_list`, confirming the model loads and runs correctly end-to-end, not only against a fake in unit tests. |

## 8. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV03-021 | AC-FV03-017 | TC-FV03-031, TC-FV03-037, TC-FV03-038 |
| FR-FV03-022 | AC-FV03-018 | TC-FV03-035, TC-FV03-036 |
| FR-FV03-023 | AC-FV03-019 | TC-FV03-032, TC-FV03-033 |
| NFR-FV03-009 | AC-FV03-020 | TC-FV03-034 |
| NFR-FV03-010 | — | (benchmark extension, no dedicated test case; see §9) |

## 9. Implementation Notes

- `rerank()`'s bare `except Exception` (§5.1) is intentionally broad, not a narrower exception type — matching the same defensive-degradation posture parent Spec FV-03 already establishes for missing evidence (FR-FV03-007's "return a warning instead of inventing facts"): a reranker failure mode is not enumerable in advance (model load failure, out-of-memory, malformed input), and the fallback behavior (pre-rerank ordering) is safe regardless of failure cause.
- TC-FV03-038 is the one test in this plan that requires the real `sentence-transformers`/`BAAI/bge-reranker-base` dependency installed and network-reachable for its first download — it should be marked or skipped in CI environments without that dependency, consistent with how this project already gates its real-LLM-backed Docker verification steps (e.g. Spec FV10.14's live-model verification) behind environment availability rather than running them unconditionally.
- NFR-FV03-010's 200ms budget is deliberately generous relative to a CPU-only `bge-reranker-base` forward pass over 10 short pairs, which typically runs well under that in practice — the margin exists to absorb variance across CI/local hardware, not because 200ms is believed to be the true floor.
