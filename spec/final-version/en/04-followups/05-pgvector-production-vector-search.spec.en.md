# Spec FV03.5: Production Vector Search with pgvector

Source design:
- [4.5 Production Vector Search with pgvector design](../../../../system_design/final-version/en/04-followups/05-pgvector-production-vector-search.en.md) (its §1 records a schema-targeting correction made after Specs FV03.1–FV03.4 were implemented — this spec reflects the corrected design, not the original draft)
- [Spec FV03.1: Unifying the Vector-Only and Hybrid Retrieval Paths, and Wiring in Real Embeddings](01-unifying-the-vector-and-hybrid-retrieval-paths.spec.en.md) (this spec's `PostgresKnowledgeVectorSource` is a second implementation of the vector-candidate-generation step that spec made pluggable in principle; this is where it actually becomes pluggable)
- [Spec FV10.1: RAG Per-User Isolation](../10-followups/01-rag-per-user-isolation.spec.en.md) (this spec's owner-isolation acceptance criteria follow directly from the cross-tenant leak that spec fixed — the same mistake class, applied to a new code path)

---

## 1. Purpose

`InMemoryKnowledgeStore`'s vector search is an unindexed linear scan over process-local, RAM-only dictionaries: a restart loses every embedding, and nothing is shared across backend replicas. This spec adds pgvector-backed storage and ANN search on `knowledge.doc_embeddings` — the real table `InMemoryKnowledgeStore` is already populated from at startup — as an optional, pluggable replacement for the in-memory scan, leaving BM25 scoring (Spec FV03.2), fusion, and reranking (Spec FV03.3) untouched.

## 2. Scope

**In scope:**
- A `pgvector` extension, a `vector`-typed column, and an HNSW index on `knowledge.doc_embeddings`.
- A `VectorCandidateSource` protocol and its `PostgresKnowledgeVectorSource` implementation, querying `knowledge.doc_embeddings`/`knowledge.doc_chunks`/`knowledge.documents` with `owner_user_id`/`allowed_roles`/`doc_type` scoping applied in SQL.
- An optional `vector_candidate_source` constructor parameter on `InMemoryKnowledgeStore`, used by `retrieve()` to narrow the candidate set before `list_chunk_records()`'s existing Python-side permission filtering runs — not instead of it.
- A backfill script populating `embedding` for every pre-existing `knowledge.doc_embeddings` row.
- An owner-isolation test verifying SQL-level `owner_user_id` scoping.

**Out of scope:**
- Shared-visibility SQL support (Spec FV10.2's file-sharing grants) — `PostgresKnowledgeVectorSource` does not grant visibility to a shared-but-not-owned document; this is a named, explicit gap (§9), not a silent one.
- Any change to BM25 scoring (Spec FV03.2), fusion weights, or reranking (Spec FV03.3) — this spec only changes where vector candidates come from.
- The retired vector-only pipeline (`VectorStore`, `EmbeddingVectorRagService`, `InMemoryVectorRagRetriever`) — entirely untouched; `PostgresKnowledgeVectorSource` implements a different, new protocol.
- Removing `_load_knowledge_store_from_db()`'s full-corpus-at-startup load into process memory — this spec makes vector *search* production-grade (ANN instead of a linear scan), it does not remove the separate concern of the whole corpus still living in a Python dict at once (§9).

## 3. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV03-029 | The `pgvector` extension MUST be enabled, and `knowledge.doc_embeddings` MUST carry a `vector`-typed `embedding` column with an HNSW index (`vector_cosine_ops`). |
| FR-FV03-030 | `PostgresKnowledgeVectorSource` MUST implement the `VectorCandidateSource` protocol defined in this spec — not the unrelated `VectorStore` protocol used by the retired vector-only pipeline. |
| FR-FV03-031 | `owner_user_id`, `allowed_roles`, and `doc_type`/`doc_types` scoping MUST be applied inside `PostgresKnowledgeVectorSource`'s SQL query itself, not as a post-retrieval filter in application code. Shared-visibility (Spec FV10.2 grants) is explicitly out of scope for this requirement (§9). |
| FR-FV03-032 | `InMemoryKnowledgeStore.retrieve()` MUST accept an optional `vector_candidate_source`. When set, it MUST narrow the candidate set to the chunk ids `top_chunk_ids()` returns, intersected with (not substituted for) `list_chunk_records()`'s existing, unchanged Python-side permission filtering. When unset, `retrieve()`'s behavior MUST be identical to before this spec. |
| FR-FV03-033 | A backfill migration MUST populate `embedding` for every `knowledge.doc_embeddings` row where it is currently `NULL`, via `InMemoryKnowledgeStore.embed_text()`. An owner-isolation test MUST verify SQL-level `owner_user_id` scoping before this source is used in production. |
| FR-FV03-034 | If `vector_candidate_source.top_chunk_ids()` raises an exception, `retrieve()` MUST fall back to the existing in-memory candidate generation for that request rather than propagating the exception or failing the request — the same "degrade, don't crash" posture Spec FV03.3's rerank fallback already establishes. |

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV03-013 | `retrieve()`'s output (candidate set, ranking, evidence list) MUST be byte-for-byte identical to its pre-Spec-FV03.5 behavior for any `InMemoryKnowledgeStore` constructed without a `vector_candidate_source` — zero behavior change for any existing deployment or test that does not opt in. |
| NFR-FV03-014 | `PostgresKnowledgeVectorSource.top_chunk_ids()` MUST be called at most once per `retrieve()` call — no duplicate round-trips to Postgres for a single request. |

## 5. Data Contracts

### 5.1 Schema Migration

```sql
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE knowledge.doc_embeddings
    ADD COLUMN IF NOT EXISTS embedding vector(1536);

CREATE INDEX IF NOT EXISTS knowledge_doc_embeddings_hnsw_idx
    ON knowledge.doc_embeddings
    USING hnsw (embedding vector_cosine_ops);
```

Added to `KNOWLEDGE_RAG_TABLES_SQL` (`migrations.py`) alongside the existing `knowledge.*` DDL, not as a separate migration file, matching this project's existing single-block-per-schema convention.

### 5.2 `VectorCandidateSource` Protocol and `PostgresKnowledgeVectorSource`

```python
class VectorCandidateSource(Protocol):
    def top_chunk_ids(
        self,
        *,
        query_vector: tuple[float, ...],
        requesting_user_id: str,
        user_role: str | None,
        doc_type: str | None,
        doc_types: tuple[str, ...],
        limit: int,
    ) -> tuple[tuple[str, float], ...]:  # (chunk_id, cosine_distance), nearest first
        ...


class PostgresKnowledgeVectorSource:
    """FR-FV03-030/031: knowledge.* schema, owner_user_id/allowed_roles/doc_type
    scoping in SQL. Does NOT implement the retired pipeline's VectorStore
    protocol, and does NOT grant shared-visibility access (§9)."""

    def __init__(self, connection_factory: Callable[[], Connection]) -> None:
        self._connection_factory = connection_factory

    def top_chunk_ids(
        self,
        *,
        query_vector: tuple[float, ...],
        requesting_user_id: str,
        user_role: str | None,
        doc_type: str | None,
        doc_types: tuple[str, ...],
        limit: int,
    ) -> tuple[tuple[str, float], ...]:
        connection = self._connection_factory()
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT c.chunk_id, e.embedding <=> %(query_vector)s AS distance
                FROM knowledge.doc_embeddings e
                JOIN knowledge.doc_chunks c ON c.chunk_id = e.chunk_id
                JOIN knowledge.documents d ON d.source_id = c.source_id
                WHERE e.embedding IS NOT NULL
                  AND (d.owner_user_id IS NULL OR d.owner_user_id = %(requesting_user_id)s)
                  AND (
                    %(user_role)s IS NULL
                    OR d.allowed_roles = '{}'
                    OR %(user_role)s = ANY(d.allowed_roles)
                  )
                  AND (%(doc_type)s IS NULL OR d.doc_type = %(doc_type)s)
                  AND (%(doc_types)s = '{}' OR d.doc_type = ANY(%(doc_types)s))
                ORDER BY e.embedding <=> %(query_vector)s
                LIMIT %(limit)s
                """,
                {
                    "query_vector": list(query_vector),
                    "requesting_user_id": requesting_user_id,
                    "user_role": user_role,
                    "doc_type": doc_type,
                    "doc_types": list(doc_types),
                    "limit": limit,
                },
            )
            rows = cur.fetchall()
        return tuple((row[0], float(row[1])) for row in rows)
```

### 5.3 `InMemoryKnowledgeStore` Integration

```python
class InMemoryKnowledgeStore:
    def __init__(
        self,
        shared_visibility_resolver=None,
        embedding_client=None,
        reranker=None,
        vector_candidate_source: "VectorCandidateSource | None" = None,  # FR-FV03-032
    ) -> None:
        ...
        self._vector_candidate_source = vector_candidate_source

    def retrieve(self, query: RetrievalQuery, trace_id: str = "") -> RetrievalResult:
        filtered_records = self.list_chunk_records(...)  # unchanged, FR-FV03-032's authority
        filtered_records = self._narrow_by_vector_candidates(filtered_records, query)
        ranked_records = self._rank_records(filtered_records, query)
        ...  # unchanged from here on (Specs FV03.2/FV03.3)

    def _narrow_by_vector_candidates(
        self,
        filtered_records: tuple[KnowledgeChunkRecord, ...],
        query: RetrievalQuery,
    ) -> tuple[KnowledgeChunkRecord, ...]:
        """FR-FV03-032/034: intersects, never replaces, list_chunk_records()'s
        own permission filtering. Any error narrows to nothing extra (falls
        back to filtered_records unchanged) rather than failing the request."""

        if self._vector_candidate_source is None:
            return filtered_records
        query_embedding = query.query_embedding or text_embedding(query.question)
        try:
            candidates = self._vector_candidate_source.top_chunk_ids(
                query_vector=query_embedding,
                requesting_user_id=query.requesting_user_id,
                user_role=query.user_role,
                doc_type=query.doc_type,
                doc_types=query.doc_types,
                limit=max(query.top_k * 4, 20),
            )
        except Exception:
            return filtered_records
        candidate_chunk_ids = {chunk_id for chunk_id, _ in candidates}
        return tuple(
            record for record in filtered_records if record.chunk.chunk_id in candidate_chunk_ids
        )
```

### 5.4 Backfill Script

```python
def backfill_knowledge_embeddings(
    connection_factory: Callable[[], Connection],
    embedding_client: EmbeddingClient,
    batch_size: int = 50,
) -> int:
    """FR-FV03-033: populates `embedding` for every knowledge.doc_embeddings
    row currently NULL, via the same embed_text()-equivalent embedding
    client Spec FV03.1 wires in — not a separate embedding code path.
    Returns the number of rows updated."""
```

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV03-027 | The migration SQL text includes `CREATE EXTENSION IF NOT EXISTS vector`, an `ALTER TABLE knowledge.doc_embeddings ADD COLUMN ... vector(1536)`, and a `CREATE INDEX ... USING hnsw` statement. |
| AC-FV03-028 | `PostgresKnowledgeVectorSource.top_chunk_ids()` executes exactly one SQL statement whose text references `owner_user_id`, `allowed_roles`, and the `<=>` distance operator. |
| AC-FV03-029 | `InMemoryKnowledgeStore` constructed with `vector_candidate_source=None` produces identical `retrieve()` output (candidate set, ranking, evidence list) to the pre-Spec-FV03.5 implementation, for the existing regression fixtures in `tests/test_knowledge_store.py`. |
| AC-FV03-030 | `InMemoryKnowledgeStore` constructed with a fake `vector_candidate_source` returning only a subset of chunk ids narrows `retrieve()`'s candidate set to that subset, intersected with (not replacing) the existing permission-filtered set. |
| AC-FV03-031 | If `vector_candidate_source.top_chunk_ids()` raises, `retrieve()` still returns a correct, non-error result using the full permission-filtered candidate set, not a propagated exception. |
| AC-FV03-032 | The backfill script updates every `knowledge.doc_embeddings` row with `embedding IS NULL`, and does not re-embed rows that already have a non-null `embedding`. |
| AC-FV03-033 | A `PostgresKnowledgeVectorSource.top_chunk_ids()` call scoped to user A's `requesting_user_id` never returns a chunk id belonging to a document owned by a different user B — verified by inspecting the executed SQL and parameters, not only the returned rows. |

## 7. Test Plan

### 7.1 Unit Tests — Schema and SQL Construction

| ID | Layer | Description |
|---|---|---|
| TC-FV03-049 | unit | The migration SQL constant contains the `pgvector` extension statement, the `ALTER TABLE knowledge.doc_embeddings` column addition, and the HNSW index statement (AC-FV03-027). |
| TC-FV03-050 | unit | `PostgresKnowledgeVectorSource.top_chunk_ids()` against a fake connection executes exactly one statement whose SQL text contains `owner_user_id`, `allowed_roles`, and `<=>` (AC-FV03-028, NFR-FV03-014). |
| TC-FV03-051 | unit | `top_chunk_ids()` parses fetched `(chunk_id, distance)` rows in the order returned, without re-sorting — the SQL's own `ORDER BY` is the sole ordering authority. |

### 7.2 Unit Tests — `InMemoryKnowledgeStore` Integration

| ID | Layer | Description |
|---|---|---|
| TC-FV03-052 | unit | `retrieve()` with `vector_candidate_source=None` reproduces every existing assertion in `tests/test_knowledge_store.py`'s pre-Spec-FV03.5 test suite unchanged (AC-FV03-029, NFR-FV03-013). |
| TC-FV03-053 | unit | `retrieve()` with a fake `vector_candidate_source` returning a two-chunk subset out of a five-chunk permission-filtered set only ranks and returns evidence from that subset (AC-FV03-030). |
| TC-FV03-054 | unit | `retrieve()` with a fake `vector_candidate_source` that (incorrectly, simulating a SQL scoping bug) returns a chunk id belonging to a document the requester cannot see still excludes it from the final result — proving `list_chunk_records()`'s Python-side filtering remains authoritative, not merely additive (defense-in-depth proof for FR-FV03-032's "intersected with, not substituted for" wording). |
| TC-FV03-055 | unit | `retrieve()` with a fake `vector_candidate_source` that raises falls back to the full permission-filtered candidate set and still returns correct evidence, not an exception (AC-FV03-031). |

### 7.3 Unit Tests — Backfill

| ID | Layer | Description |
|---|---|---|
| TC-FV03-056 | unit | `backfill_knowledge_embeddings()` against a fake connection with a mix of `NULL` and populated `embedding` rows updates only the `NULL` ones, calling the embedding client once per updated row (AC-FV03-032). |

### 7.4 Unit Test — Owner Isolation

| ID | Layer | Description |
|---|---|---|
| TC-FV03-057 | unit | `top_chunk_ids()` called with `requesting_user_id="user_a"` executes SQL whose captured parameters include `"user_a"` bound to the `owner_user_id` predicate — confirmed against a fake connection recording executed SQL/params, per this project's existing `FakeRagPostgresConnection`-style test double convention (AC-FV03-033). |

## 8. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV03-029 | AC-FV03-027 | TC-FV03-049 |
| FR-FV03-030 | AC-FV03-028 | TC-FV03-050, TC-FV03-051 |
| FR-FV03-031 | AC-FV03-033 | TC-FV03-057 |
| FR-FV03-032 | AC-FV03-029, AC-FV03-030 | TC-FV03-052, TC-FV03-053, TC-FV03-054 |
| FR-FV03-033 | AC-FV03-032, AC-FV03-033 | TC-FV03-056, TC-FV03-057 |
| FR-FV03-034 | AC-FV03-031 | TC-FV03-055 |
| NFR-FV03-013 | AC-FV03-029 | TC-FV03-052 |
| NFR-FV03-014 | — | TC-FV03-050 |

## 9. Implementation Notes

- **Named limitation, not a silent one:** `PostgresKnowledgeVectorSource` does not grant visibility to a document shared via Spec FV10.2's approval workflow but not owned by the requester — `top_chunk_ids()`'s SQL only expresses `owner_user_id`/`allowed_roles`/`doc_type`, the filters that already have a column to query against. TC-FV03-054 is deliberately designed to prove the Python-side `list_chunk_records()` filter still catches anything the SQL filter under- or over-includes, precisely because this gap exists — this spec does not claim SQL-level parity with the full permission model, only that the narrowing step never widens access beyond what `list_chunk_records()` already allows.
- **A second named limitation:** this spec makes the *search* step production-grade (an HNSW ANN index instead of an O(n) linear scan), but does not address `_load_knowledge_store_from_db()` loading every document/chunk/embedding into a process-local Python dict at startup — at a corpus size large enough to need pgvector's ANN search in the first place, loading the whole corpus into memory on every backend replica is itself a real scaling ceiling this spec does not remove. That is a follow-up this spec's own scope deliberately excludes, not an oversight.
- FR-FV03-034's fallback (§5.3's bare `except Exception`) mirrors Spec FV03.3's reranker fallback exactly, for the same reason: a Postgres connectivity or query failure is not enumerable in advance, and degrading to the existing in-memory candidate set is always safe, never worse than failing the request outright.
- TC-FV03-057's owner-isolation test is intentionally a unit test against a fake connection (capturing executed SQL/parameters), not a live-database integration test — this project has no Postgres instance available in its current CI/test environment (confirmed by every existing Postgres-dependent test already being skipped/failing there for that reason). This spec's acceptance criteria are scoped to what a fake-connection test can actually prove: that the correct SQL is constructed and parameterized. A live-database verification of this spec's migration and query, once a real Postgres instance is available, is a deployment-verification step this spec's own test plan cannot substitute for.
