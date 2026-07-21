# 4.3 Adding a Real Cross-Encoder Rerank Stage

## 1. Problem Solved

`InMemoryKnowledgeStore.retrieve()`'s own docstring already claims a four-stage pipeline: `"""Run filter -> hybrid retrieval -> rerank -> dedupe -> evidence output."""` (`src/chatbi/knowledge.py:281`). There is no rerank stage. What the code actually does after hybrid scoring is dedupe-and-truncate the *same* scores computed one step earlier. This document builds the missing stage: a genuine second-pass re-scoring of a narrowed candidate set using a cross-encoder model, which reads query and chunk together (unlike the bi-encoder/keyword scores in [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.en.md)/[4.2](02-bm25-keyword-scoring.en.md), which score each independently and compare afterward).

## 2. What Already Exists

`retrieve()` (`knowledge.py:280-313`) currently does:

```python
ranked_records = self._rank_records(filtered_records, query)                      # hybrid score
selected_records = self._dedupe_adjacent_chunks(ranked_records[: max(query.top_k * 2, query.top_k)])
selected_records = selected_records[: query.top_k]                                 # truncate
```

`_dedupe_adjacent_chunks` removes near-duplicate neighboring chunks from the same document; it does not call a model or recompute any score. The `reranked_count` field already present on `RetrievalStats` (`src/chatbi/core/contracts.py:149`) is populated with `len(ranked_records)` (`knowledge.py:308`) — today it just means "how many records had a hybrid score computed," not "how many went through an actual rerank pass." This field is already wired through to the API/telemetry layer, which makes it the natural place to report real rerank activity once it exists, rather than adding a new field.

## 3. Design

1. **Insert the rerank step between hybrid scoring and dedupe, over the narrowed 2×`top_k` candidate window** — the same window `retrieve()` already carves out at line 294, so the added cost is bounded regardless of corpus size: reranking never runs on more than `2 * top_k` chunks.
2. **Model choice: a cross-encoder, run locally, not called out to an external API.** `sentence-transformers`' `CrossEncoder` wrapping `BAAI/bge-reranker-base` is CPU-viable at this candidate-set size (a couple dozen pairs per query, not thousands) and keeps the design consistent with [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.en.md)'s in-process model, avoiding a new network dependency and its own latency/availability failure mode on the request's critical path.
3. **Score `(question, chunk_text)` pairs directly** — this is the entire point of a cross-encoder over the existing bi-encoder cosine score: it can attend to query and chunk jointly, catching relevance signals (negation, exact-entailment, precise clause matching) that independently-computed embeddings miss.
4. **Re-sort the narrowed set by the cross-encoder score, then run `_dedupe_adjacent_chunks` and truncate to `top_k`** exactly as today — dedupe stays a pure post-processing step, unchanged.
5. **`reranked_count` now means what its name says**: the number of candidates that actually passed through the cross-encoder, i.e. `min(len(filtered_records), 2 * query.top_k)`. No API/contract change needed — the field already exists and is already surfaced; only its populated value changes to be accurate.
6. **Failure mode:** if the reranker model fails to load or errors on a request, fall back to the pre-rerank hybrid ordering rather than failing the whole retrieval — evidence with slightly worse ranking is strictly better than no evidence, consistent with this project's existing "degrade, don't crash" pattern elsewhere in the orchestrator (see `PlanExecutor`'s handling of non-critical agent failures, and [07 Resilience and Scale](../07-resilience-and-scale.en.md) more generally).

## 4. Effort Estimate

Roughly **1.5–2 person-days**: the code change itself is small (one new step, bounded input size, an existing field to populate correctly), but this phase carries the only new runtime dependency in the plan (a local model download/load) and needs a fallback path tested, which is where most of the time goes.

## 5. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV03-021 | `retrieve()` must re-score the top `2 * top_k` hybrid-ranked candidates with a cross-encoder model before dedupe and truncation. | Implemented |
| FR-FV03-022 | `RetrievalStats.reranked_count` must reflect the number of candidates that actually passed through the cross-encoder rerank pass. | Implemented |
| FR-FV03-023 | If the reranker is unavailable or errors, retrieval must fall back to the pre-rerank hybrid ordering rather than failing the request. | Implemented |
