# 4.2 Replacing Jaccard Keyword Overlap with Real BM25 Scoring

## 1. Problem Solved

The "keyword" half of the hybrid retrieval formula is not actually a term-weighting algorithm — it is a plain set-intersection ratio that treats every token as equally important. A rare, high-signal domain term (e.g. a specific insurance-clause phrase) scores no higher than any common word the query happens to share with a chunk. This document replaces it with BM25, the standard term-frequency/inverse-document-frequency ranking function, without changing the surrounding hybrid-fusion architecture from [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.en.md).

## 2. What Already Exists

`InMemoryKnowledgeStore._rank_records()` (`src/chatbi/knowledge.py:341-363`) computes, per candidate chunk:

```python
keyword_score = keyword_overlap_score(query_tokens, text_tokens(record.chunk.chunk_text))
vector_score = cosine_similarity(...)
relevance_score = round((keyword_score * 0.60) + (vector_score * 0.35) + source_score, 4)
```

`keyword_overlap_score()` (`knowledge.py:505-511`) is:

```python
return len(query_set & chunk_set) / len(query_set)
```

This is a query-coverage ratio (closer to a recall-oriented Jaccard variant), not BM25: it has no term-frequency weighting (a term appearing 5 times in a chunk scores the same as appearing once), no inverse-document-frequency weighting (a rare term across the corpus scores the same as a common one), and no document-length normalization (a short, precisely on-topic chunk scores the same as a long chunk that happens to contain the same token set). `text_tokens()` (`knowledge.py:501-502`) tokenizes with `re.findall(r"[a-z0-9]+", text.lower())` — ASCII-only, so this also silently drops all Chinese-character tokens from keyword scoring today, a real gap for a platform whose interview-answer transcripts and much of its own spec corpus are in Chinese.

No occurrence of "BM25" or "inverted index" exists anywhere in `src/` (confirmed by repo-wide search) — this is a net-new algorithm, not a rename.

## 3. Design

1. **Add `rank_bm25` as a dependency** (pure-Python `BM25Okapi`, no external service — appropriate given the project's current in-memory retrieval scale; revisit only if the corpus grows past what fits comfortably in a single process).
2. **Build the BM25 index over the *already permission-filtered* candidate set**, not a global pre-built index. `_rank_records()` receives `filtered_records` — the output of `list_chunk_records()` (`knowledge.py:218-255`), which has already applied org/role/owner visibility filtering. BM25 must score within that same scoped candidate list, otherwise a document a user cannot see could still influence corpus-wide IDF statistics in a way that leaks its existence. Concretely: `BM25Okapi([tokenize(r.chunk.chunk_text) for r in filtered_records])`, built fresh per request. This trades a small amount of CPU per query for correctness; it is not a persistent index, so there is no staleness/invalidation problem to manage.
3. **Replace Chinese-blind tokenization.** Extend `text_tokens()`'s pattern (or add a parallel tokenizer used only for BM25) to also emit CJK unigrams/bigrams, so Chinese-language chunks and questions actually participate in keyword scoring instead of contributing zero tokens.
4. **Normalize BM25's unbounded raw scores into the existing `[0, 1]`-ish fusion.** BM25 scores are not naturally bounded like cosine similarity is; min-max normalize each query's raw BM25 scores across its own candidate set before applying the existing `* 0.60` weight, so the fixed-weight fusion formula's assumptions (both terms roughly comparable in scale) continue to hold.
5. **Keep the 0.60/0.35/source_score weights unchanged in this document**, same rationale as [4.1 §3.4](01-unifying-the-vector-and-hybrid-retrieval-paths.en.md#3-design) — re-tuning needs the evaluation harness from [4.4](04-golden-dataset-hit-rate-and-mrr-evaluation.en.md) to be measured rather than guessed.

## 4. Effort Estimate

Roughly **0.5–1 person-day**. This is the cheapest of the four phases: it is a local, drop-in replacement of one scoring function behind an existing seam (`_rank_records` already isolates "the keyword score" as one line), no new infrastructure, and the CJK tokenizer extension is the only part requiring care (verify against at least one Chinese-language knowledge document already in the seed data).

## 5. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV03-018 | Keyword scoring must use BM25 (term-frequency/inverse-document-frequency/length-normalized), computed over the permission-filtered candidate set per request, not a pre-built global index. | Implemented |
| FR-FV03-019 | Keyword tokenization must support Chinese-language text, not only ASCII word tokens. | Implemented |
| FR-FV03-020 | BM25 scores must be normalized into a comparable range with the existing cosine-similarity term before the 0.60/0.35 fusion weights are applied. | Implemented |
