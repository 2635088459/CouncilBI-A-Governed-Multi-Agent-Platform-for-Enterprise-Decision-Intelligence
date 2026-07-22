# Spec FV03.6: A Real-Business Golden Dataset, and an Embedding-Reload Efficiency Fix

Source design:
- [4.6 A Real-Business Golden Dataset, and an Embedding-Reload Efficiency Fix design](../../../../system_design/final-version/en/04-followups/06-real-golden-dataset-and-embedding-reload-fix.en.md)
- [Spec FV03.4: A Golden Dataset and Automated Hit Rate / MRR Evaluation for Retrieval](04-golden-dataset-hit-rate-and-mrr-evaluation.spec.en.md) (this spec replaces that spec's synthetic 50-case fixture with a real, schema-grounded dataset — `hit_rate_at_k()`, `reciprocal_rank()`, `RetrievalEvaluator` themselves are unchanged)
- [Spec FV03.5: Production Vector Search with pgvector](05-pgvector-production-vector-search.spec.en.md) (this spec's embedding-reload fix reads the vector `PostgresKnowledgeVectorSource` was already writing there; `parse_pgvector_embedding()` mirrors that spec's `::vector` cast discipline for reads instead of writes)

---

## 1. Purpose

A code-review pass run after Specs FV03.1–FV03.5 were implemented, tested, and wired into the running application found two further gaps: `_load_knowledge_store_from_db()` recomputed every chunk's embedding via a real `EmbeddingClient` on every process restart, even when Spec FV03.5's backfill migration had already computed and persisted the exact vector; and Spec FV03.4's Golden Dataset was an entirely invented 50-case fixture with no relationship to this platform's real seeded content, so it validated the Hit Rate@K/MRR *mechanism* but said nothing about actual retrieval quality. This spec fixes the reload path and replaces the synthetic dataset with a real, schema-grounded, self-verified one.

## 2. Scope

**In scope:**
- Reading the persisted `knowledge.doc_embeddings.embedding` column instead of recomputing it, when a `vector_candidate_source` (Spec FV03.5) is configured.
- Ten new real business documents in `migrations.py`'s seed data, grounded in this platform's actual business tables and governance subsystems.
- A 24-question Golden Dataset stored as an external JSON file (`golden_dataset/cases.json`), loadable via `load_golden_dataset_cases()`.
- Wiring `handle_eval_run()`'s expected-chunk-id lookup to the loaded Golden Dataset by exact question match.
- Self-verification: every label checked by actually running `retrieve()` against the real seeded content.

**Out of scope:**
- Any change to `RetrievalEvaluator`, `hit_rate_at_k()`, `reciprocal_rank()`, or `EvaluationScorer`'s metric-breakdown wiring (Spec FV03.4) — this spec only changes the *data* fed into that unchanged mechanism.
- Any change to `PostgresKnowledgeVectorSource`'s query logic, the `pgvector` schema, or the backfill migration itself (Spec FV03.5) — this spec only adds a read path for the vector that migration already writes.
- Mining real production questions to grow the Golden Dataset further — that is Spec FV03.7's concern.
- Persisting the Golden Dataset to Postgres, or building an admin UI for editing it — the file lives in `src/chatbi/golden_dataset/cases.json` precisely so a JSON edit + PR review is the whole workflow; no additional tooling is in scope.

## 3. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV03-035 | `_load_knowledge_store_from_db()` MUST read the persisted `knowledge.doc_embeddings.embedding` column when a `VectorCandidateSource` is configured for the deployment, falling back to `embed_text()` recomputation only for a chunk whose persisted embedding is `NULL`. Deployments without pgvector configured (`vector_candidate_source is None`) MUST NOT attempt to `SELECT` this column, and MUST reproduce the pre-this-spec query and behavior exactly. |
| FR-FV03-036 | The Golden Dataset MUST be stored as an external, versioned data file (`golden_dataset/cases.json`), loadable via `load_golden_dataset_cases()`, not as Python literals inside test or application code. |
| FR-FV03-037 | Every Golden Dataset `(question, expected_chunk_ids)` label MUST reference a document actually seeded into `knowledge.documents`/`knowledge.doc_chunks` by `migrations.py` (not a synthetic in-memory-only fixture), and MUST be verified by actually running `retrieve()` against that content before being trusted. |
| FR-FV03-038 | `handle_eval_run()`'s expected-chunk-id lookup MUST match a question exactly (case-insensitive, whitespace-trimmed) against the loaded Golden Dataset, not via ad hoc keyword heuristics. A question with no exact match MUST return an empty tuple, opting that case out of retrieval scoring (mirroring `expected_sql_fragments`' existing convention). |

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV03-015 | For any `InMemoryKnowledgeStore` reload where `vector_candidate_source` is `None`, `_load_knowledge_store_from_db()`'s query and resulting store state MUST be byte-for-byte identical to its pre-Spec-FV03.6 behavior — zero behavior change for any deployment that has not opted into Spec FV03.5's pgvector search. |
| NFR-FV03-016 | The full 24-case Golden Dataset MUST score Hit Rate@3 = MRR = 1.0 when run against an `InMemoryKnowledgeStore` seeded with the exact content `migrations.py`'s `KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL` writes to production — a label that does not achieve this is a labeling defect, not an acceptable dataset entry. |

## 5. Data Contracts

### 5.1 `_load_knowledge_store_from_db()`'s Reload Branch

```python
def _load_knowledge_store_from_db(
    connect_fn: Callable[[str], Any],
    database_url: str,
    embedding_client: EmbeddingClient | None = None,
    reranker: CrossEncoderReranker | None = None,
    vector_candidate_source: VectorCandidateSource | None = None,
) -> InMemoryKnowledgeStore:
    store = InMemoryKnowledgeStore(
        embedding_client=embedding_client, reranker=reranker,
        vector_candidate_source=vector_candidate_source,
    )
    try:
        conn = connect_fn(database_url)
        with conn.cursor() as cur:
            # ... documents SELECT unchanged ...
            if vector_candidate_source is not None:  # FR-FV03-035
                cur.execute(
                    "SELECT c.chunk_id, c.source_id, c.chunk_index, c.chunk_text,"
                    " e.embedding::text"
                    " FROM knowledge.doc_chunks c"
                    " LEFT JOIN knowledge.doc_embeddings e ON e.chunk_id = c.chunk_id"
                    " ORDER BY c.source_id, c.chunk_index"
                )
                for chunk_id, source_id, chunk_index, chunk_text, embedding_text in cur.fetchall():
                    embedding_vector = (
                        parse_pgvector_embedding(embedding_text)
                        if embedding_text is not None
                        else store.embed_text(chunk_text)  # NULL — not yet backfilled
                    )
                    _save_chunk_and_embedding(store, chunk_id, source_id, chunk_index, chunk_text, embedding_vector)
            else:  # NFR-FV03-015: unchanged query and behavior
                cur.execute(
                    "SELECT chunk_id, source_id, chunk_index, chunk_text"
                    " FROM knowledge.doc_chunks ORDER BY source_id, chunk_index"
                )
                for chunk_id, source_id, chunk_index, chunk_text in cur.fetchall():
                    _save_chunk_and_embedding(store, chunk_id, source_id, chunk_index, chunk_text, store.embed_text(chunk_text))
    except Exception:
        pass  # DB not ready yet; fall back to empty store
    return store
```

`parse_pgvector_embedding(value: str) -> tuple[float, ...]` (`knowledge_postgres_vector_source.py`) parses pgvector's canonical text output (`"[0.1,0.2,0.3]"`) — the same `::vector`/`::text` cast discipline Spec FV03.5 established for writes, applied here to reads, since no pgvector Python type adapter is registered anywhere in this project.

### 5.2 The Golden Dataset File and Loader

```python
# evaluation_cases.py
_GOLDEN_DATASET_CASES_PATH = Path(__file__).parent / "golden_dataset" / "cases.json"

def load_golden_dataset_cases(path: Path | None = None) -> tuple[EvalCase, ...]:
    """FR-FV03-036/037: loads the real-business retrieval Golden Dataset.
    Every (question, expected_chunk_ids) pair was verified by actually
    running retrieve() against the real seeded content."""

    active_path = path or _GOLDEN_DATASET_CASES_PATH
    raw_cases = json.loads(active_path.read_text(encoding="utf-8"))
    return load_eval_cases(raw_cases)  # unchanged existing parser
```

`golden_dataset/cases.json` is bundled under `src/chatbi/`, not a top-level repository folder, because `Dockerfile.backend` only `COPY`s `src/` into the production image (FR-FV03-036).

Ten new documents in `migrations.py`'s `KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL` (added to `BASE_MIGRATION_SQL_STATEMENTS`), each grounded in a real table from `data_model.py`'s business catalog (`refunds`, `marketing_campaigns`, `products`, `customers`/`support_tickets`, `regions`, `web_events`) or this codebase's own governance subsystems (SQL guardrail, PII masking, release gate), plus the two pre-existing documents — twelve total.

### 5.3 `handle_eval_run()`'s Expected-Chunk-Id Lookup

```python
@lru_cache(maxsize=1)
def _golden_dataset_expected_chunk_ids_by_question() -> Mapping[str, tuple[str, ...]]:
    return {
        case.question.strip().lower(): case.expected_chunk_ids
        for case in load_golden_dataset_cases()
    }


class ChatBIApplication:
    def _expected_chunk_ids_for_question(self, question: str) -> tuple[str, ...]:
        # FR-FV03-038: exact match, not a keyword heuristic
        return _golden_dataset_expected_chunk_ids_by_question().get(question.strip().lower(), ())
```

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV03-034 | `_load_knowledge_store_from_db()` with `vector_candidate_source` configured and a non-`NULL` persisted `embedding` for a chunk populates that chunk's `ChunkEmbedding.embedding_vector` from `parse_pgvector_embedding()`'s output, and never calls the configured `EmbeddingClient` for that chunk. |
| AC-FV03-035 | The same, for a chunk whose persisted `embedding` is `NULL`, falls back to `store.embed_text(chunk_text)`, calling the configured `EmbeddingClient` exactly once for that chunk. |
| AC-FV03-036 | `_load_knowledge_store_from_db()` with `vector_candidate_source=None` executes the original `SELECT chunk_id, source_id, chunk_index, chunk_text ...` query (no `embedding` column referenced) and produces identical store state to the pre-Spec-FV03.6 implementation. |
| AC-FV03-037 | `load_golden_dataset_cases()` loads exactly 24 `EvalCase` objects from the bundled JSON file, each with a non-empty `case_id`, `question`, and `expected_chunk_ids`, and no duplicate `case_id`s. |
| AC-FV03-038 | Every `expected_chunk_ids` entry across all 24 loaded cases references a `chunk_id` that exists in the twelve real seeded documents (`KNOWLEDGE_RAG_SEED_SQL` + `KNOWLEDGE_RAG_GOLDEN_DATASET_SEED_SQL`). |
| AC-FV03-039 | `RetrievalEvaluator` run against an `InMemoryKnowledgeStore` seeded with content mirroring the twelve real documents scores `retrieval_hit_rate == 1.0` and `retrieval_mrr == 1.0` for the full 24-case dataset. |
| AC-FV03-040 | `_expected_chunk_ids_for_question()` returns the correct `expected_chunk_ids` for a question that exactly matches (case-insensitive, trimmed) one of the 24 Golden Dataset questions, and returns `()` for any question that does not. |

## 7. Test Plan

### 7.1 Unit Tests — Embedding Reload

| ID | Layer | Description |
|---|---|---|
| TC-FV03-058 | unit | `_load_knowledge_store_from_db()` against a fake cursor returning a non-`NULL` `embedding::text` value populates the chunk's embedding via `parse_pgvector_embedding()` and never invokes an `EmbeddingClient` fake that raises if called (AC-FV03-034). |
| TC-FV03-059 | unit | The same, with a `NULL` `embedding::text` value, invokes a fake `EmbeddingClient` exactly once and uses its returned vector (AC-FV03-035). |
| TC-FV03-060 | unit | `_load_knowledge_store_from_db()` with `vector_candidate_source=None` executes the original query shape and reproduces pre-Spec-FV03.6 store state exactly, against the same fixture data used by the pre-existing test suite (AC-FV03-036, NFR-FV03-015). |

### 7.2 Unit Tests — Golden Dataset Loading and Validity

| ID | Layer | Description |
|---|---|---|
| TC-FV03-061 | unit | `load_golden_dataset_cases()` returns 24 cases with unique `case_id`s and non-empty `expected_chunk_ids` for every case (AC-FV03-037). |
| TC-FV03-062 | unit | Every `expected_chunk_ids` entry across all loaded cases is a member of the known chunk-id set mirroring the twelve real seeded documents (AC-FV03-038). |
| TC-FV03-063 | unit | `RetrievalEvaluator.evaluate()`/`.aggregate()` run against a store seeded with the twelve real documents' exact content reports `retrieval_hit_rate == 1.0` and `retrieval_mrr == 1.0` for the full dataset (AC-FV03-039, NFR-FV03-016). |

### 7.3 Unit Tests — Expected-Chunk-Id Lookup

| ID | Layer | Description |
|---|---|---|
| TC-FV03-064 | unit | `handle_eval_run()` with a question exactly matching one of the Golden Dataset's own canonical questions computes non-`None` `retrieval_hit_rate`/`retrieval_mrr` in `metric_breakdown`, scored against a live `InMemoryKnowledgeStore` seeded with the matching real document; a suite whose questions match no Golden Dataset entry omits these keys entirely (AC-FV03-040). |

## 8. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV03-035 | AC-FV03-034, AC-FV03-035 | TC-FV03-058, TC-FV03-059 |
| FR-FV03-036 | AC-FV03-037 | TC-FV03-061 |
| FR-FV03-037 | AC-FV03-038, AC-FV03-039 | TC-FV03-062, TC-FV03-063 |
| FR-FV03-038 | AC-FV03-040 | TC-FV03-064 |
| NFR-FV03-015 | AC-FV03-036 | TC-FV03-060 |
| NFR-FV03-016 | AC-FV03-039 | TC-FV03-063 |

## 9. Implementation Notes

- The one real mislabel found and fixed during authoring (a first-draft question about revenue "spiking" retrieved the marketing-campaign document ahead of the intended revenue-policy document, since both share the tokens "revenue"/"campaign"/"month") is not itself a numbered acceptance criterion — NFR-FV03-016's "must score 1.0" bar is what would have caught it, and did.
- `golden_dataset/cases.json`'s placement under `src/chatbi/` rather than a top-level `golden_dataset/` folder (more consistent with where `spec/`/`system_design/` live) is a deliberate placement decision recorded in the source design's §3.3, not an oversight — verified against `Dockerfile.backend`'s `COPY src ./src` line.
- This spec deliberately does not attempt to also fix `runtime.agent_traces` having no writer, or extend the Golden Dataset with real production questions — both are named, out-of-scope gaps carried into Spec FV03.7 (mining) and left unaddressed elsewhere respectively, not silently folded into this spec's acceptance criteria.
