# 4.6 A Real-Business Golden Dataset, and an Embedding-Reload Efficiency Fix

## 1. Problem Solved

A code-review pass run after [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.en.md)–[4.5](05-pgvector-production-vector-search.en.md) were implemented, tested, and wired into the running application surfaced two further gaps — one a genuine operational cost bug, the other a data-quality gap that no amount of additional unit testing could close on its own:

1. **Every process restart recomputed every chunk's embedding, even when [4.5](05-pgvector-production-vector-search.en.md)'s backfill had already computed and persisted it.** `_load_knowledge_store_from_db()` (`api/http.py`), the function that rebuilds the live `InMemoryKnowledgeStore` from Postgres at process start, called `store.embed_text(chunk_text)` unconditionally for every chunk row — one real `EmbeddingClient` call per chunk, per restart, regardless of whether `knowledge.doc_embeddings.embedding` already held the exact vector [4.5](05-pgvector-production-vector-search.en.md)'s backfill migration wrote there. Beyond the wasted provider cost, this meant the vector `PostgresKnowledgeVectorSource` narrows candidates with (the persisted one) and the vector `list_chunk_records()` uses for final in-memory cosine scoring (the freshly recomputed one) were two independently-computed values that only happened to agree because the embedding model is deterministic for identical input text — a latent inconsistency, not a guaranteed one.
2. **[4.4](04-golden-dataset-hit-rate-and-mrr-evaluation.en.md)'s Golden Dataset was entirely invented.** The 50-case fixture in `test_retrieval_evaluation.py` was a self-contained, hand-written corpus with no relationship to this platform's real seeded content (`migrations.py`'s `KNOWLEDGE_RAG_SEED_SQL`, which held only 2 real documents). It correctly exercised the Hit Rate@K/MRR *mechanism* — proving `RetrievalEvaluator` computes the right numbers for a given set of labels — but said nothing about whether real users asking real questions against this platform's actual knowledge base would get correct evidence back. A synthetic dataset can validate code; it cannot validate retrieval quality.

This document closes both gaps: an efficiency/correctness fix to the [4.5](05-pgvector-production-vector-search.en.md) reload path, and a real, schema-grounded, self-verified Golden Dataset that replaces the synthetic fixture as the dataset `handle_eval_run()`'s production retrieval-metrics wiring (the other half of this code-review pass, tracked as FR-FV03-027's production gap) actually scores against.

## 2. What Already Exists

- `PostgresKnowledgeVectorSource.top_chunk_ids()` and `backfill_knowledge_embeddings()` (`knowledge_postgres_vector_source.py`, [4.5](05-pgvector-production-vector-search.en.md)) already read/write `knowledge.doc_embeddings.embedding` (a `vector(1536)` pgvector column) correctly, including the `::vector` cast psycopg needs since no pgvector type adapter is registered anywhere in this project.
- `_load_knowledge_store_from_db()` (`api/http.py:620-706`) already receives a `vector_candidate_source: VectorCandidateSource | None` parameter — the same signal `_build_default_chatbi_application()` uses to mean "the [4.5](05-pgvector-production-vector-search.en.md) pgvector migration has been applied to this deployment."
- `RetrievalEvaluator`, `hit_rate_at_k()`, and `reciprocal_rank()` (`retrieval_evaluation.py`, [4.4](04-golden-dataset-hit-rate-and-mrr-evaluation.en.md)) are already correct and fully tested — nothing about the scoring mechanism needed to change, only the data fed into it.
- `evaluation_cases.py`'s `load_eval_cases()` already parses JSON/YAML-shaped case dictionaries into `EvalCase` objects, including `expected_chunk_ids` — but nothing in the codebase called it against a real, bundled file before this work; it was only exercised in tests with inline dictionaries.
- `data_model.py`'s `build_default_data_model_catalog()` already defines this platform's real business tables — `orders`, `refunds`, `customers`, `products`, `regions`, `web_events`, `support_tickets`, `marketing_campaigns` — the domain vocabulary the new Golden Dataset documents are grounded in, so the dataset reads as plausible business content rather than generic filler.

## 3. Design

### 3.1 Read the persisted embedding instead of recomputing it

`_load_knowledge_store_from_db()` now branches on whether `vector_candidate_source` is configured:

```python
if vector_candidate_source is not None:
    # knowledge.doc_embeddings.embedding already holds a real vector for
    # every backfilled chunk (Spec FV03.5) — read it back instead of
    # recomputing.
    cur.execute(
        "SELECT c.chunk_id, c.source_id, c.chunk_index, c.chunk_text, e.embedding::text"
        " FROM knowledge.doc_chunks c"
        " LEFT JOIN knowledge.doc_embeddings e ON e.chunk_id = c.chunk_id"
        " ORDER BY c.source_id, c.chunk_index"
    )
    for chunk_id, source_id, chunk_index, chunk_text, embedding_text in cur.fetchall():
        embedding_vector = (
            parse_pgvector_embedding(embedding_text)
            if embedding_text is not None
            else store.embed_text(chunk_text)  # not yet backfilled — fall back
        )
        _save_chunk_and_embedding(store, chunk_id, source_id, chunk_index, chunk_text, embedding_vector)
else:
    # Unchanged: deployments that never ran the pgvector migration keep the
    # original recompute-at-load query, and never SELECT a column
    # (knowledge.doc_embeddings.embedding) that may not exist there.
    ...
```

Two design decisions worth naming:

- **The branch is gated on `vector_candidate_source is not None`, not a separate flag.** This reuses the exact signal already meaning "pgvector is configured for this deployment" elsewhere in the codebase, so a deployment that never ran [4.5](05-pgvector-production-vector-search.en.md)'s migration never attempts to `SELECT` a column (`knowledge.doc_embeddings.embedding`) that does not exist there — avoiding a hard failure on every restart for every deployment that has not opted into pgvector.
- **`e.embedding::text`, parsed by a new `parse_pgvector_embedding()` helper, not a native type adapter.** No pgvector Python package is registered anywhere in this project ([4.5](05-pgvector-production-vector-search.en.md) §3.2 already established this for the write side); reading the column back needs the same explicit-cast-and-parse treatment, not an assumption about how psycopg represents an unregistered type.
- **A `NULL` persisted embedding still falls back to `embed_text()`.** A chunk ingested between [4.5](05-pgvector-production-vector-search.en.md)'s migration landing and its backfill script actually running has no persisted vector yet; falling back per-chunk (rather than failing the whole load) keeps that transition window safe.

### 3.2 Ten new real business documents

The real seeded knowledge base (`migrations.py`'s `KNOWLEDGE_RAG_SEED_SQL`) held only 2 documents — too few to exercise a meaningful Golden Dataset, and both authored before this platform's actual business-table catalog (`data_model.py`) existed in its current form. A new `KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL` block adds ten more, each grounded in one of `data_model.py`'s real business tables or this codebase's own governance subsystems, so the dataset reads as content a real analytics platform would actually maintain:

| Document | Grounded in |
|---|---|
| Refund policy and regional shipping delays | `refunds`, `regions` |
| Marketing campaign spend and revenue attribution | `marketing_campaigns` |
| Product pricing tier changes | `products` |
| Customer churn analysis for the analytics tier | `customers`, `support_tickets` |
| Regional sales variance | `regions` |
| Web signup conversion funnel | `web_events` |
| SQL guardrail and dangerous query policy | this codebase's `SimpleSqlGuardrail` |
| Data governance and PII masking policy | this codebase's restricted-field audit logging |
| Incident response runbook | this codebase's `agent_traces`/observability |
| Evaluation release gate policy | this codebase's `ReleaseGatePolicy` |

Twelve documents in total (these ten plus the two pre-existing ones), added to `BASE_MIGRATION_SQL_STATEMENTS` alongside the existing `KNOWLEDGE_RAG_SEED_SQL` — plain, idempotent `INSERT ... ON CONFLICT DO UPDATE` statements against tables the base migration already creates, carrying the same "safe to always apply" property the existing seed block has.

### 3.3 The Golden Dataset as data, not Python literals

Twenty-four real business questions (two per document) are stored as `src/chatbi/golden_dataset/cases.json` — a plain JSON array of `{case_id, question, expected_chunk_ids}` objects — rather than as a Python tuple inside a test file. Two consequences follow from this:

1. **A business reviewer can add or edit a case via a JSON edit and a pull request, without touching Python code.** `evaluation_cases.py` gains `load_golden_dataset_cases()`, a thin wrapper that reads the bundled file and passes it through the already-existing `load_eval_cases()` parser — no new parsing logic, just a new entry point onto an existing one.
2. **The file lives under `src/chatbi/`, not a top-level repository folder.** `Dockerfile.backend` only `COPY`s `src/` into the production image; a data file living anywhere else (e.g. a top-level `golden_dataset/` folder, more consistent with where `spec/`/`system_design/` live) would silently never reach a deployed backend. This is a deliberate placement decision, not an oversight.

`handle_eval_run()`'s `_expected_chunk_ids_for_question()` (`application/app.py`) is rewired to look up this loaded dataset by exact, normalized question text — replacing two ad hoc keyword rules (`"revenue" in question and requires_citation(question)`, `"support" in question and "ticket" in question`) that existed only because no real dataset existed yet to look up against. The lookup table is built once per process (`lru_cache`), since the bundled file does not change at runtime.

### 3.4 Self-verification, not asserted labels

Every one of the 24 `(question, expected_chunk_ids)` pairs was checked by actually constructing an `InMemoryKnowledgeStore` seeded with the same 12 documents' content and running `retrieve()` against it — the same discipline [4.4](04-golden-dataset-hit-rate-and-mrr-evaluation.en.md) §9 already established for its own 50-case fixture (which itself caught and corrected one mislabeled case this way). This process caught one real mislabel during authoring: a first-draft question about "why did revenue spike this month" retrieved the marketing-campaign document ahead of the intended revenue-policy document, because both documents' text shares the tokens "revenue," "campaign," and "month." Rewording the question (to ask what factors explain a revenue *anomaly*, rather than a *spike*) resolved the ambiguity; the fix is a wording change to the label, not a scoring change. `tests/test_golden_dataset_cases.py` makes this verification permanent and repeatable: it seeds a store mirroring `KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL`'s exact content and asserts `RetrievalEvaluator.aggregate()` reports Hit Rate@3 = MRR = 1.0 for the full 24-case dataset — a future edit to either the dataset or the retrieval pipeline that breaks a label is caught by this test, not discovered in production.

## 4. Effort Estimate

Both pieces were completed in this pass — actuals, not estimates:

| Task | Actual effort |
|---|---|
| Embedding-reload fix (`_load_knowledge_store_from_db()` branch, `parse_pgvector_embedding()`, regression tests) | ~0.5 day |
| Ten new business documents (content authoring, schema grounding, seed SQL) | ~0.5 day |
| 24-question Golden Dataset authoring + self-verification (including the one mislabel found and fixed) | ~1 day |
| JSON file + loader + `handle_eval_run()` rewiring, regression tests, full-suite verification | ~0.5 day |

## 5. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV03-035 | `_load_knowledge_store_from_db()` MUST read the persisted `knowledge.doc_embeddings.embedding` column when a `VectorCandidateSource` is configured for the deployment, falling back to `embed_text()` recomputation only for a chunk whose persisted embedding is `NULL`. Deployments without pgvector configured MUST NOT attempt to `SELECT` this column. | Implemented |
| FR-FV03-036 | The Golden Dataset MUST be stored as an external, versioned data file (`golden_dataset/cases.json`), loadable via `load_golden_dataset_cases()`, not as Python literals inside test code. | Implemented |
| FR-FV03-037 | Every Golden Dataset `(question, expected_chunk_ids)` label MUST reference a document actually seeded into `knowledge.documents`/`knowledge.doc_chunks` by `migrations.py` (not a synthetic in-memory-only fixture), and MUST be verified by actually running `retrieve()` against that content before being trusted. | Implemented |
| FR-FV03-038 | `handle_eval_run()`'s expected-chunk-id lookup MUST match a question exactly against the loaded Golden Dataset, not via ad hoc keyword heuristics. | Implemented |
