# 4.1 Unifying the Vector-Only and Hybrid Retrieval Paths, and Wiring in Real Embeddings

## 1. Problem Solved

The platform currently ships **two separate, non-communicating retrieval mechanisms** behind `RagAgentRunner`, and only one of them does hybrid (keyword + vector) scoring — the other is vector-only. Depending on which one happens to be wired in, "real embeddings" and "hybrid scoring" never actually run together. This document unifies them into one retrieval path so that the hybrid formula already designed in [4 Embedding, Vector Search, and RAG](../04-embedding-vector-rag.en.md) actually runs on real semantic vectors in production, not on a placeholder.

## 2. What Already Exists

`RagAgentRunner.run()` (`src/chatbi/agents/rag_agent.py:62-82`) tries two retrieval mechanisms **in a fixed priority order**:

1. `_retrieve_vector_if_possible()` (line 84-114) — runs first if `vector_retriever` is set. It calls `InMemoryVectorRagRetriever.retrieve()` (line 176-207), which embeds the question and does a pure `VectorStore.search()` (cosine only). **No keyword scoring happens on this path at all.**
2. `_retrieve_if_possible()` (line 116-137) — only runs if (1) was skipped (`vector_retriever is None`). This calls `InMemoryKnowledgeStore.retrieve()` (`src/chatbi/knowledge.py:280-313`), which *does* compute the hybrid score `keyword_score * 0.60 + vector_score * 0.35 + source_score` (`knowledge.py:356-362`).

The catch: `InMemoryKnowledgeStore.ingest_document()` (`knowledge.py:180-216`) hardcodes a local `text_embedding()` call to produce each chunk's stored vector — a deterministic hash-bucket pseudo-embedding (`knowledge.py`'s own `text_embedding`/`_text_embedding` family, same technique as `embedding_vector_rag.py:584-591`), **not** a real embedding model. There is no constructor or method parameter on `InMemoryKnowledgeStore` that accepts an `EmbeddingClient`. Meanwhile, a real embedding provider already exists and is wired for the *other* path: `OpenAIEmbeddingClient` (`src/chatbi/embedding_vector_config.py:19-63`) calls the real OpenAI embeddings API and is selected via `runtime_config.embedding_provider == "openai"` (`embedding_vector_config.py:74-81`) — but that wiring only feeds `EmbeddingVectorRagService`/`InMemoryVectorRagRetriever` (path 1, the vector-only one), never `InMemoryKnowledgeStore` (path 2, the hybrid one).

Net effect: whichever path actually executes for a given `RagAgentRunner` instance, at least one property (real semantic meaning, or keyword-aware scoring) is missing. Silently — nothing errors, nothing warns; `run()` just quietly takes whichever branch `vector_retriever is None` sends it down.

## 3. Design

**Decision: retire the vector-only path as `RagAgentRunner`'s primary mechanism; make the hybrid path the one and only production retrieval path, and give it a real embedding client.**

1. **Give `InMemoryKnowledgeStore` an injectable embedding client.** Add `embedding_client: EmbeddingClient | None = None` to `InMemoryKnowledgeStore.__init__` and to `ingest_document(...)`. When provided, call `embedding_client.embed(EmbeddingRequest(input_texts=(text,)))` and store `response.vectors[0]` instead of calling the local `text_embedding()`. When omitted, keep today's deterministic hash-bucket behavior unchanged — this keeps every existing test in `tests/test_knowledge_store.py` and `tests/test_rag_agent.py` green without modification, since none of them pass an `embedding_client`.
2. **Wire `OpenAIEmbeddingClient` into whatever populates the knowledge store at startup**, gated by the same `runtime_config.embedding_provider` flag `embedding_vector_config.py` already reads — one embedding-provider setting now controls both call sites instead of only one.
3. **Stop constructing `RagAgentRunner` with a non-`None` `vector_retriever` in the main orchestrator's fanout wiring.** `_retrieve_vector_if_possible()` and `InMemoryVectorRagRetriever` are not deleted — `rag_v2.py`/`api/http.py`'s separate evidence pipeline can keep using them if that pipeline has its own reasons to stay vector-only — but the orchestrator's `RagAgentRunner` construction must always pass `vector_retriever=None` so `_retrieve_if_possible()` (the hybrid path) is the one that runs. This single change is what actually closes the gap: today, if anyone ever wires a `vector_retriever` into the orchestrator's `RagAgentRunner` to "add real embeddings," they will have silently disabled hybrid scoring instead of improving it.
4. **Do not change the 0.60/0.35/source_score fusion weights in this document.** Swapping in real vectors changes the *meaning* of `vector_score` but not the formula; re-tuning the weights is deferred to [4.4 Golden Dataset, Hit Rate, and MRR Evaluation](04-golden-dataset-hit-rate-and-mrr-evaluation.en.md), once there is a labeled dataset to tune against instead of guessing.

## 4. Effort Estimate

Roughly **1.5–2 person-days**: adding the optional constructor/method parameter and the real-client call site is small and mechanical; most of the time goes to tracing every place that currently constructs `InMemoryKnowledgeStore`/`RagAgentRunner` (orchestrator wiring, any seed/demo scripts, tests) and updating each deliberately rather than by find-and-replace, since a couple of call sites *should* keep the deterministic mock (fast, offline tests) on purpose.

## 5. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV03-014 | `InMemoryKnowledgeStore` must accept an optional `EmbeddingClient` and use it for chunk embedding when provided, falling back to the existing deterministic hash-bucket embedding when not. | Proposed |
| FR-FV03-015 | The knowledge-store ingestion path must read the same `runtime_config.embedding_provider`/`embedding_model` settings the vector-only pipeline already reads, so one configuration switch controls both. | Proposed |
| FR-FV03-016 | The orchestrator's `RagAgentRunner` construction must always pass `vector_retriever=None`, so the hybrid-scoring path is the only retrieval mechanism reachable from a live chat query. | Proposed |
| FR-FV03-017 | This change must not regress any existing `test_knowledge_store.py` / `test_rag_agent.py` test — those tests continue to exercise the deterministic embedding path by omitting `embedding_client`. | Proposed |
