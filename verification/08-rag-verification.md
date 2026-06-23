# Verification: 08 RAG Retrieval and Evidence

This document records the current machine-verifiable status for `spec/version1/08-rag.spec.md`.

## Scope

Verified workflow:

```text
business document text
  -> clean_document_text
  -> chunk_text with overlap
  -> deterministic local embedding
  -> InMemoryKnowledgeStore
  -> metadata and role filtering
  -> hybrid keyword + vector scoring
  -> reranking
  -> adjacent chunk merge
  -> EvidenceItem with citation_anchor, publish_time, and relevance_score
  -> RagAgentRunner
  -> SimpleOrchestrator
  -> QueryAnswer and API response with evidence_uncertainty and retrieval_stats
```

Covered implementation files:

| Area | File |
|---|---|
| Core evidence and retrieval contracts | `src/chatbi/core/contracts.py` |
| In-memory document ingestion and retrieval | `src/chatbi/knowledge.py` |
| RAG agent adapter | `src/chatbi/agents/rag_agent.py` |
| Orchestrator integration | `src/chatbi/orchestration/simple_orchestrator.py` |
| API response mapping | `src/chatbi/api/models.py` |

## Covered Requirements

| Requirement | Verification |
|---|---|
| `FR-08-001` | `tests/test_knowledge_store.py::test_knowledge_store_saves_document_chunk_and_embedding`; `tests/test_knowledge_store.py::test_knowledge_store_returns_evidence_items_with_source_id_and_snippet` |
| `FR-08-002` | `tests/test_knowledge_store.py::test_knowledge_store_filters_chunks_by_doc_type_and_publish_time` |
| `FR-08-003` | `tests/test_rag_agent.py::test_rag_agent_retrieves_evidence_for_question_payload`; hybrid scoring is implemented in `InMemoryKnowledgeStore._rank_records` |
| `FR-08-004` | `tests/test_rag_agent.py::test_rag_agent_retrieves_evidence_for_question_payload`; reranked count is exposed through `RetrievalStats` |
| `FR-08-005` | `tests/test_knowledge_store.py::test_retrieval_merges_adjacent_chunks_from_same_document` |
| `FR-08-006` | `tests/test_rag_agent.py::test_rag_agent_requires_citation_anchor`; `tests/test_simple_orchestrator.py::test_orchestrator_uses_knowledge_store_for_rag_evidence` |
| `FR-08-007` | `tests/test_rag_agent.py::test_rag_agent_returns_uncertainty_when_retrieval_has_no_evidence`; `tests/test_simple_orchestrator.py::test_orchestrator_marks_uncertainty_when_rag_retrieval_has_no_evidence` |
| `FR-08-008` | `tests/test_knowledge_store.py::test_retrieval_excludes_out_of_permission_documents`; `tests/test_simple_orchestrator.py::test_orchestrator_filters_rag_evidence_by_request_role` |
| `NFR-08-001` | `RetrievalStats.latency_ms` is recorded; full P95 benchmark load testing is future work |
| `NFR-08-002` | Citation anchors are required and tested; benchmark-level citation coverage measurement is future work |
| `NFR-08-003` | No-evidence uncertainty is tested; benchmark-level unsupported-claim-rate measurement is future work |
| `NFR-08-004` | `save_document`, `save_chunk`, `save_embedding`, and `ingest_document` support incremental in-memory updates |

## Acceptance Criteria

| Acceptance Criterion | Verification |
|---|---|
| `AC-08-001` | `tests/test_simple_orchestrator.py::test_orchestrator_uses_knowledge_store_for_rag_evidence` verifies a why-question returns evidence with a valid citation anchor |
| `AC-08-002` | `tests/test_simple_orchestrator.py::test_orchestrator_marks_uncertainty_when_rag_retrieval_has_no_evidence` verifies zero accessible evidence returns `evidence_uncertainty=True` |
| `AC-08-003` | `tests/test_simple_orchestrator.py::test_orchestrator_filters_rag_evidence_by_request_role` verifies restricted evidence is excluded for unauthorized roles |
| `AC-08-004` | `tests/test_knowledge_store.py::test_retrieval_merges_adjacent_chunks_from_same_document` verifies adjacent chunks from the same document are merged |
| `AC-08-005` | `RetrievalStats.latency_ms` is captured for every retrieval; P95 load verification remains future work |

## Test Plan Mapping

| Test Case | Current Verification |
|---|---|
| `TC-08-001` | `tests/test_knowledge_store.py::test_chunk_text_uses_configured_overlap` |
| `TC-08-002` | `tests/test_knowledge_store.py::test_knowledge_store_filters_chunks_by_doc_type_and_publish_time` |
| `TC-08-003` | `tests/test_rag_agent.py::test_rag_agent_retrieves_evidence_for_question_payload`; `tests/test_simple_orchestrator.py::test_orchestrator_uses_knowledge_store_for_rag_evidence` |
| `TC-08-004` | `tests/test_rag_agent.py::test_rag_agent_returns_uncertainty_when_retrieval_has_no_evidence`; `tests/test_simple_orchestrator.py::test_orchestrator_marks_uncertainty_when_rag_retrieval_has_no_evidence` |
| `TC-08-005` | `tests/test_knowledge_store.py::test_retrieval_excludes_out_of_permission_documents`; `tests/test_simple_orchestrator.py::test_orchestrator_filters_rag_evidence_by_request_role` |
| `TC-08-006` | `RetrievalStats.latency_ms` provides per-request timing; benchmark P95 test is not implemented in the in-memory MVP |

## Design Notes

The current RAG slice is intentionally in-memory and deterministic.

In plain terms:

1. `knowledge.py` is the small local library: it stores documents, chunks text, creates lightweight embeddings, filters, scores, reranks, and returns evidence.
2. `rag_agent.py` is the assistant that asks the library for evidence and shapes the result into an agent payload.
3. `simple_orchestrator.py` is the classroom coordinator: it passes the user question, SQL/metric context, role, and trace id into the RAG agent.
4. `api/models.py` exposes the spec-level output fields so API callers can see evidence, uncertainty, retrieval stats, confidence, and trace id.

This implementation does not use a real vector database, external embedding model, cross-encoder reranker, live crawler, or human-labeled benchmark. Those are outside the current in-memory MVP scope or listed as open questions in the spec.

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Focused static check:

```bash
.venv/bin/pyright src/chatbi/core/contracts.py src/chatbi/knowledge.py tests/test_knowledge_store.py
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Focused test suite:

```bash
.venv/bin/pytest tests/test_knowledge_store.py tests/test_rag_agent.py tests/test_simple_orchestrator.py tests/test_api_models.py tests/test_overall_architecture.py
```

Result:

```text
44 passed
```

Full test suite:

```bash
.venv/bin/pytest
```

Result:

```text
244 passed, 1 warning
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient
```

This warning comes from the third-party FastAPI/TestClient stack and does not indicate a failing project test.
