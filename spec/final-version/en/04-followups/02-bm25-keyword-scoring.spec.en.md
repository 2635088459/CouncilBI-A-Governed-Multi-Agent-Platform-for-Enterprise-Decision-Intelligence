# Spec FV03.2: Replacing Jaccard Keyword Overlap with Real BM25 Scoring

Source design:
- [4.2 Replacing Jaccard Keyword Overlap with Real BM25 Scoring design](../../../../system_design/final-version/en/04-followups/02-bm25-keyword-scoring.en.md)
- [Spec FV03.1: Unifying the Vector-Only and Hybrid Retrieval Paths, and Wiring in Real Embeddings](01-unifying-the-vector-and-hybrid-retrieval-paths.spec.en.md) (this spec's BM25 term is fused with FV03.1's real `vector_score` via the unchanged `0.60`/`0.35` weights)

---

## 1. Purpose

`InMemoryKnowledgeStore._rank_records()`'s "keyword" score is a plain query-token-coverage ratio (`len(query_set & chunk_set) / len(query_set)`), not a term-weighting algorithm: it has no term-frequency weighting, no inverse-document-frequency weighting, and no document-length normalization, and its ASCII-only tokenizer silently drops all Chinese-language tokens. This spec replaces it with BM25, computed per request over the permission-filtered candidate set, and fixes the CJK tokenization gap.

## 2. Scope

**In scope:**
- A BM25-based keyword scorer (`rank_bm25`'s `BM25Okapi`), built fresh per request over `list_chunk_records()`'s already permission-filtered output.
- A tokenizer extension that emits CJK tokens alongside the existing ASCII word tokens.
- Min-max normalization of raw BM25 scores into a range comparable to the existing `[0, 1]`-bounded `cosine_similarity` term before fusion.

**Out of scope:**
- Any change to vector/cosine scoring (Spec FV03.1) or reranking (Spec FV03.3).
- Any change to the `0.60`/`0.35`/`source_score` fusion weight constants.
- A persistent or pre-built BM25 index — this spec's index is rebuilt per request against the already-filtered candidate set (see §9).
- Any external search service (ElasticSearch or similar) — see [4.5 Production Vector Search with pgvector design](../../../../system_design/final-version/en/04-followups/05-pgvector-production-vector-search.en.md) §3 for why this is deliberately not pursued.

## 3. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV03-018 | Keyword scoring MUST use BM25 (Okapi BM25 or an equivalent term-frequency/inverse-document-frequency/length-normalized formula), computed over exactly the `filtered_records` candidate set `list_chunk_records()` returns for the current request. It MUST NOT be computed over, and MUST NOT let corpus-wide inverse-document-frequency statistics leak information about, any document outside that permission-filtered set. |
| FR-FV03-019 | Keyword tokenization used for BM25 scoring MUST tokenize Chinese-language text into scoreable units (at minimum CJK unigrams), not only ASCII `[a-z0-9]+` tokens. |
| FR-FV03-020 | Raw BM25 scores for a request's candidate set MUST be normalized (e.g. min-max across that request's own candidates) into a range comparable to the existing `[0, 1]`-bounded `cosine_similarity` term before the `0.60`/`0.35` fusion weights (unchanged from parent Spec FV-03 and Spec FV03.1) are applied. |

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV03-007 | BM25 index construction and scoring for a single request's permission-filtered candidate set of up to 1,000 chunks (matching `rag_benchmark.py`'s `build_mock_rag_service` default corpus size) MUST add no more than 50ms to P95 per-request retrieval latency. |
| NFR-FV03-008 | A chunk containing only Chinese-language text MUST NOT score `0.0` on the keyword term purely due to tokenization — a chunk containing a query-relevant Chinese term MUST produce a nonzero raw BM25 score for a query sharing that term. |

## 5. Data Contracts

### 5.1 Tokenizer and BM25 Scorer

```python
def cjk_and_ascii_tokens(text: str) -> tuple[str, ...]:
    """FR-FV03-019: emits ASCII word tokens (matching the existing
    text_tokens() behavior) plus CJK unigrams, so Chinese-language
    chunks/questions are not silently dropped from keyword scoring."""
    ascii_tokens = re.findall(r"[a-z0-9]+", text.lower())
    cjk_tokens = re.findall(r"[一-鿿]", text)
    return tuple(ascii_tokens) + tuple(cjk_tokens)


def normalize_scores(raw_scores: tuple[float, ...]) -> tuple[float, ...]:
    """FR-FV03-020: min-max normalization; an all-equal input (including a
    single-candidate corpus) maps to all zeros rather than dividing by zero."""
    if not raw_scores:
        return raw_scores
    lo, hi = min(raw_scores), max(raw_scores)
    if hi == lo:
        return tuple(0.0 for _ in raw_scores)
    return tuple((score - lo) / (hi - lo) for score in raw_scores)


class Bm25CandidateScorer:
    """FR-FV03-018: built fresh per request over filtered_records — no
    persistent/global index, no cross-request or cross-tenant statistics
    leakage."""

    def __init__(self, filtered_records: tuple[KnowledgeChunkRecord, ...]) -> None:
        self._records = filtered_records
        corpus = [cjk_and_ascii_tokens(r.chunk.chunk_text) for r in filtered_records]
        self._bm25 = BM25Okapi(corpus)

    def scores(self, query_tokens: tuple[str, ...]) -> tuple[float, ...]:
        raw_scores = tuple(self._bm25.get_scores(list(query_tokens)))
        return normalize_scores(raw_scores)
```

### 5.2 `_rank_records` Integration

```python
def _rank_records(self, filtered_records, query):
    scorer = Bm25CandidateScorer(filtered_records)
    query_tokens = cjk_and_ascii_tokens(query.question)
    keyword_scores = scorer.scores(query_tokens)
    for record, keyword_score in zip(filtered_records, keyword_scores):
        vector_score = cosine_similarity(...)  # unchanged, Spec FV03.1
        source_score = _source_weight(record.document.doc_type)
        relevance_score = round((keyword_score * 0.60) + (vector_score * 0.35) + source_score, 4)
        ...
```

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV03-013 | For a query containing a rare domain term present in exactly one candidate chunk, that chunk's raw (pre-normalization) BM25 score MUST be strictly greater than a chunk matched only by an equally-frequent but corpus-common term — regression-proves BM25's IDF weighting is active, unlike the prior Jaccard overlap, which would have scored both candidates identically whenever token-set-intersection size was equal. |
| AC-FV03-014 | A chunk containing only Chinese text and a Chinese-language question sharing at least one CJK token produce a nonzero raw BM25 score for that chunk. |
| AC-FV03-015 | Normalized keyword scores for any single request's candidate set fall within `[0.0, 1.0]`. |
| AC-FV03-016 | `_rank_records()`'s BM25 index is rebuilt for every `retrieve()` call scoped to a different `org_id`/permission context — no candidate from a prior, differently-scoped request's index composition influences the current request's scores. |

## 7. Test Plan

### 7.1 Unit Tests — BM25 Scorer

| ID | Layer | Description |
|---|---|---|
| TC-FV03-023 | unit | `Bm25CandidateScorer.scores()` for a corpus with one chunk containing a rare term and another containing only common terms ranks the rare-term chunk with a higher raw score for a query containing that rare term (AC-FV03-013). |
| TC-FV03-024 | unit | `cjk_and_ascii_tokens()` for a mixed Chinese/English string returns both ASCII word tokens and individual CJK characters, matching the existing ASCII-tokenization output for the ASCII portion. |
| TC-FV03-025 | unit | `normalize_scores()` for an all-equal input returns all zeros, not a division-by-zero error. |
| TC-FV03-026 | unit | `normalize_scores()` for a range of raw scores maps the maximum to `1.0` and the minimum to `0.0` (AC-FV03-015). |

### 7.2 Unit Tests — `_rank_records` Integration

| ID | Layer | Description |
|---|---|---|
| TC-FV03-027 | unit | `_rank_records()` for a Chinese-language chunk and a Chinese question sharing a CJK term produces `relevance_score > source_score` alone, i.e. `keyword_score` contributed a nonzero amount (AC-FV03-014). |
| TC-FV03-028 | unit | `_rank_records()` constructs a new `Bm25CandidateScorer` per call — verified by asserting two calls with different `filtered_records` produce independently-built BM25 corpora (AC-FV03-016). |

### 7.3 Integration Tests

| ID | Layer | Description |
|---|---|---|
| TC-FV03-029 | integration | `InMemoryKnowledgeStore.retrieve()` for a query matching a rare domain term ranks the chunk containing that term above chunks matched only by common words shared with the query, end-to-end through `retrieve()`'s existing filter → rank → dedupe pipeline. |
| TC-FV03-030 | integration negative | `retrieve()` scoped to org A's permission context returns an unchanged relevance score for a chunk shared in kind with org B's corpus, regardless of how many additional chunks containing the same term are seeded under org B — confirms no cross-tenant IDF leakage (AC-FV03-016). |

## 8. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV03-018 | AC-FV03-013, AC-FV03-016 | TC-FV03-023, TC-FV03-028, TC-FV03-029, TC-FV03-030 |
| FR-FV03-019 | AC-FV03-014 | TC-FV03-024, TC-FV03-027 |
| FR-FV03-020 | AC-FV03-015 | TC-FV03-025, TC-FV03-026 |
| NFR-FV03-007 | — | (benchmark extension, no dedicated test case; see §9) |
| NFR-FV03-008 | AC-FV03-014 | TC-FV03-027 |

## 9. Implementation Notes

- NFR-FV03-007's latency budget is verified by extending `rag_benchmark.py`'s existing benchmark harness rather than a new dedicated unit test — consistent with how parent Spec FV-03's own `NFR-FV03-001` is itself verified only by `TC-FV03-008`, a benchmark test, not a unit test.
- `normalize_scores()`'s all-equal-input branch (TC-FV03-025) matters in practice whenever a candidate set is small (e.g. a single-chunk knowledge base for a newly onboarded org) — `BM25Okapi` degenerates to identical or near-identical scores in that case, and a naive min-max normalization would otherwise divide by zero.
- Chinese tokenization uses per-character unigrams rather than a real word segmenter (e.g. `jieba`) deliberately: per-character n-grams are a defensible, zero-new-dependency baseline for CJK information retrieval, and this spec does not introduce a new runtime dependency purely for tokenization quality. Revisit only if AC-FV03-014-style tests reveal segmentation-sensitive false matches in practice — that would be a follow-up to this spec, not a gap in it.
- FR-FV03-018's "no persistent index" decision (also noted in the source design's §2/§3) means BM25 statistics are recomputed on every `retrieve()` call. This is the direct trade — a small amount of per-query CPU for the guarantee that a user's IDF exposure is always scoped exactly to what `list_chunk_records()` already filtered for them — rather than the correctness risk of a stale or over-broad pre-built index. Spec FV03.5 (pgvector; not part of this spec set) is the place a future durability/performance concern with this approach would be addressed, if real usage ever demonstrates one.
