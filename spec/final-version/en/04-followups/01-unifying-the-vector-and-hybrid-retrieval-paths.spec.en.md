# Spec FV03.1: Unifying the Vector-Only and Hybrid Retrieval Paths, and Wiring in Real Embeddings

Source design:
- [4.1 Unifying the Vector-Only and Hybrid Retrieval Paths, and Wiring in Real Embeddings design](../../../../system_design/final-version/en/04-followups/01-unifying-the-vector-and-hybrid-retrieval-paths.en.md)
- [Spec FV-03: Embedding and Vector RAG](../03-embedding-vector-rag.spec.en.md) (parent spec; this spec extends its `EmbeddingClient`/`VectorStore` contracts (FR-FV03-001) to a second, pre-existing retrieval path that parent spec did not cover)

---

## 1. Purpose

`RagAgentRunner.run()` currently reaches one of two mutually exclusive retrieval mechanisms depending on whether a `vector_retriever` happens to be injected: a vector-only path with no keyword scoring, or a hybrid (keyword + vector) path whose stored vectors are a deterministic hash-bucket placeholder, never a real embedding model's output. This spec makes the hybrid path the only one reachable from a live chat query, and gives it real embeddings, so the hybrid-scoring formula parent Spec FV-03 already defines the building blocks for actually governs production relevance ranking.

## 2. Scope

**In scope:**
- An optional `embedding_client: EmbeddingClient | None` parameter on `InMemoryKnowledgeStore.__init__` and `ingest_document()`, used for chunk embedding when provided.
- Wiring `OpenAIEmbeddingClient` (already defined per parent Spec FV-03 §5) into the knowledge-store ingestion call site, gated by the existing `runtime_config.embedding_provider` setting.
- Changing the main orchestrator's `RagAgentRunner` construction to always pass `vector_retriever=None`.

**Out of scope:**
- Any change to the `VectorStore`/`EmbeddingClient` protocol signatures defined in parent Spec FV-03.
- Deleting `InMemoryVectorRagRetriever` or `_retrieve_vector_if_possible()` — `rag_v2.py`/`api/http.py`'s separate evidence pipeline may continue constructing and using them independently of the orchestrator's `RagAgentRunner`.
- Any change to keyword scoring (Spec FV03.2 handles BM25) or reranking (Spec FV03.3).
- Re-tuning the `0.60`/`0.35`/`source_score` fusion weights — deferred to Spec FV03.4, once a labeled evaluation baseline exists.

## 3. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV03-014 | `InMemoryKnowledgeStore` MUST accept an optional `embedding_client: EmbeddingClient \| None = None` constructor parameter and an equivalent optional parameter on `ingest_document()`. When either is provided (the method-level parameter taking precedence), chunk embedding MUST call `embedding_client.embed(...)` and store the returned vector. When neither is provided, the existing deterministic hash-bucket `text_embedding()` behavior MUST be preserved unchanged. |
| FR-FV03-015 | The knowledge-store ingestion call site MUST read the same `runtime_config.embedding_provider` / `runtime_config.embedding_model` settings already used to select an embedding provider for the vector-only pipeline (parent Spec FV-03 §5.5), so one configuration switch selects the provider for both call sites. |
| FR-FV03-016 | The main orchestrator's construction of `RagAgentRunner` MUST always pass `vector_retriever=None`, so `_retrieve_if_possible()` (the hybrid path) is the only retrieval mechanism reachable from a live `POST /api/v2/chat/query` request routed to the RAG agent. |
| FR-FV03-017 | This change MUST NOT regress any existing test in `tests/test_knowledge_store.py` or `tests/test_rag_agent.py` — those tests continue to omit `embedding_client` and MUST continue to exercise the deterministic hash-bucket embedding path unchanged. |

## 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV03-005 | `RagAgentRunner.run()`'s behavior for a request that never reaches the RAG agent (e.g. an SQL-only question with no RAG-classified intent) MUST be unaffected by FR-FV03-016 — the change is confined to which branch runs *inside* `RagAgentRunner`, not to routing upstream of it. |
| NFR-FV03-006 | Calling `InMemoryKnowledgeStore.ingest_document()` with a real `embedding_client` MUST NOT change its return type, its side effects on `_chunks_by_chunk_id`, or the shape of the `KnowledgeChunkRecord` tuples it returns — only the embedding *values* stored change, not the ingestion contract. |

## 5. Data Contracts

### 5.1 `InMemoryKnowledgeStore` Constructor and Ingestion

```python
class InMemoryKnowledgeStore:
    def __init__(
        self,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._embedding_client = embedding_client
        # existing _documents_by_source_id / _chunks_by_chunk_id / _embeddings_by_chunk_id unchanged

    def ingest_document(
        self,
        document: KnowledgeDocument,
        raw_text: str,
        chunk_size: int = 90,
        chunk_overlap: int = 15,
        embedding_client: EmbeddingClient | None = None,
    ) -> tuple[KnowledgeChunkRecord, ...]:
        """FR-FV03-014: the method-level embedding_client argument takes
        precedence over the constructor-level one; if neither is given,
        falls back to the existing deterministic text_embedding()."""
        active_client = embedding_client or self._embedding_client
        ...
        for index, text in enumerate(chunks, start=1):
            vector = (
                active_client.embed(EmbeddingRequest(input_texts=(text,))).vectors[0]
                if active_client is not None
                else text_embedding(text)
            )
            embedding = ChunkEmbedding(
                embedding_id=f"{document.source_id}_embedding_{index}",
                chunk_id=chunk.chunk_id,
                embedding_vector=vector,
            )
            ...
```

### 5.2 Orchestrator Wiring

```python
# orchestration wiring for the live chat-query path
rag_agent_runner = RagAgentRunner(
    knowledge_store=knowledge_store,
    vector_retriever=None,  # FR-FV03-016: hybrid path is the only reachable one
    ...
)
```

### 5.3 Runtime-Config-Driven Ingestion Wiring

```python
def build_knowledge_store_embedding_client(
    runtime_config: RuntimeConfig,
) -> EmbeddingClient | None:
    """FR-FV03-015: reuses the same provider switch
    build_embedding_vector_rag_service_from_runtime_config() (parent Spec
    FV-03 §5.5) already reads."""
    if runtime_config.embedding_provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        model = runtime_config.embedding_model or "text-embedding-3-small"
        return OpenAIEmbeddingClient(api_key=api_key, model=model)
    if runtime_config.embedding_provider == "mock":
        return None  # ingest_document() falls back to text_embedding()
    raise ValueError(f"Unsupported embedding provider: {runtime_config.embedding_provider}")
```

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV03-009 | `InMemoryKnowledgeStore(embedding_client=SomeRealClient()).ingest_document(...)` stores `ChunkEmbedding.embedding_vector` equal to `SomeRealClient().embed(...).vectors[0]` for the chunk's text, not the hash-bucket `text_embedding()` output. |
| AC-FV03-010 | `InMemoryKnowledgeStore().ingest_document(...)` (no `embedding_client` supplied anywhere) stores the same `embedding_vector` values as before this spec — byte-identical to the pre-change deterministic hash-bucket output for a fixed input text. |
| AC-FV03-011 | A live `chat_query_v2` request that reaches the RAG agent never takes the `_retrieve_vector_if_possible()` branch — verified by asserting `RagAgentRunner.vector_retriever is None` at construction, and by confirming `retrieve()` (the hybrid path) executes for a spy/mock `InMemoryKnowledgeStore`. |
| AC-FV03-012 | Setting `runtime_config.embedding_provider = "openai"` causes both the vector-only pipeline (parent Spec FV-03's existing behavior) and the knowledge-store ingestion path to construct an `OpenAIEmbeddingClient` with the same `model` value. |

## 7. Test Plan

### 7.1 Unit Tests — `InMemoryKnowledgeStore` Embedding Injection

| ID | Layer | Description |
|---|---|---|
| TC-FV03-015 | unit | `ingest_document()` with a fake `EmbeddingClient` stores the fake client's returned vector as the chunk's `embedding_vector`, not `text_embedding()`'s output (AC-FV03-009). |
| TC-FV03-016 | unit | `ingest_document()` with no `embedding_client` passed and none set on the constructor stores exactly the same `embedding_vector` values as the current, pre-spec implementation, for a fixed input text (AC-FV03-010, regression guard). |
| TC-FV03-017 | unit | Every existing test in `tests/test_knowledge_store.py` continues to pass unmodified (FR-FV03-017). |

### 7.2 Unit Tests — Runtime-Config Wiring

| ID | Layer | Description |
|---|---|---|
| TC-FV03-018 | unit | `build_knowledge_store_embedding_client()` with `embedding_provider="openai"` returns an `OpenAIEmbeddingClient` configured with `runtime_config.embedding_model` (AC-FV03-012). |
| TC-FV03-019 | unit | `build_knowledge_store_embedding_client()` with `embedding_provider="mock"` returns `None`. |
| TC-FV03-020 | unit | `build_knowledge_store_embedding_client()` with an unsupported provider string raises `ValueError`, matching the existing error-handling convention in `build_embedding_vector_rag_service_from_runtime_config()`. |

### 7.3 Integration Tests — Orchestrator Wiring

| ID | Layer | Description |
|---|---|---|
| TC-FV03-021 | integration | Constructing the orchestrator's fanout runners for a RAG-classified question yields a `RagAgentRunner` with `vector_retriever is None` (AC-FV03-011). |
| TC-FV03-022 | integration | `POST /api/v2/chat/query` for a RAG-classified question, with `InMemoryKnowledgeStore.retrieve()` instrumented as a spy, records exactly one call to `retrieve()` and zero calls to any `VectorRagRetriever.retrieve()` implementation. |

## 8. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV03-014 | AC-FV03-009 | TC-FV03-015 |
| FR-FV03-015 | AC-FV03-012 | TC-FV03-018, TC-FV03-019, TC-FV03-020 |
| FR-FV03-016 | AC-FV03-011 | TC-FV03-021, TC-FV03-022 |
| FR-FV03-017 | AC-FV03-010 | TC-FV03-016, TC-FV03-017 |
| NFR-FV03-005 | AC-FV03-011 | TC-FV03-022 |
| NFR-FV03-006 | AC-FV03-010 | TC-FV03-016 |

## 9. Implementation Notes

- FR-FV03-014's `ingest_document()`-level `embedding_client` parameter taking precedence over the constructor-level one (§5.1) is a deliberate design choice, not an oversight: it lets a single `InMemoryKnowledgeStore` instance ingest some documents with a real embedding client and others (e.g. synthetic test fixtures) with the deterministic fallback, without constructing two separate store instances.
- This spec does not touch `_rank_records()`'s fusion formula at all — swapping in real vectors changes what `vector_score` measures (genuine semantic similarity instead of token-hash overlap) but the `0.60`/`0.35`/`source_score` weights and the rest of the ranking pipeline are byte-for-byte unchanged. Any apparent relevance-ranking change after this spec ships is a signal the *fusion weights* may need retuning (Spec FV03.4's job), not a defect in this spec.
- `InMemoryVectorRagRetriever`/`_retrieve_vector_if_possible()` are intentionally left in the codebase, not deleted, because `rag_v2.py`/`api/http.py` construct and use them independently for a separate evidence pipeline outside the main orchestrator's `RagAgentRunner` — deleting them would be an unrelated, larger change out of this spec's scope.
