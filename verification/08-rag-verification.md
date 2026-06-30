# Verification: 08 RAG Retrieval and Evidence Explanation v2

This document records the current machine-verifiable status for
`spec/version2/08-rag.spec.md`.

## Scope

Verified RAG v2 workflow:

```text
IndexDocumentRequest
  -> typed document contract and validation
  -> deterministic clean/chunk pipeline
  -> embedding metadata generation
  -> short document synchronous indexing
  -> long document queued indexing job
  -> worker-driven queued job completion
  -> repository persistence boundary
  -> PostgreSQL row mapping and migration DDL

EvidenceSearchRequest
  -> time-window, business-tag, and permission-tag filtering
  -> keyword relevance ranking over permitted chunks
  -> EvidenceItem with evidence_id, document_id, chunk_id, snippet, source, date, score
  -> EvidenceEvent persisted by trace_id
  -> RAG_NO_EVIDENCE empty recall behavior
  -> cited RagExplanation and RagAnswer
```

Covered implementation files:

| Area | File |
|---|---|
| Typed RAG v2 contracts | `src/chatbi/rag.py` |
| Deterministic indexing helpers | `src/chatbi/rag_indexing.py` |
| Evidence retrieval and permission filtering | `src/chatbi/rag_retrieval.py` |
| Service facade | `src/chatbi/rag_service.py` |
| Cited explanation builder | `src/chatbi/rag_explanation.py` |
| Answering use case | `src/chatbi/rag_answering.py` |
| Repository boundary, in-memory store, PostgreSQL store | `src/chatbi/rag_repository.py` |
| PostgreSQL DDL and row mappers | `src/chatbi/rag_postgres_rows.py` |
| Worker adapter for queued indexing | `src/chatbi/rag_worker.py` |
| Benchmark helper | `src/chatbi/rag_benchmark.py` |
| Public facade | `src/chatbi/rag_v2.py` |
| Runnable demo | `examples/rag_v2_demo.py` |
| Migration and data model integration | `src/chatbi/migrations.py`, `src/chatbi/data_model.py` |

Legacy v1 RAG remains in `src/chatbi/knowledge.py` and
`src/chatbi/agents/rag_agent.py`. The v2 implementation is exposed through
`chatbi.rag_v2` to avoid confusing the two `EvidenceItem` contract families.

## Covered Requirements

| Requirement | Verification |
|---|---|
| `VR-08-001` | Permission-tag filtering is enforced before ranking. See `tests/test_rag_v2_workflow.py::test_rag_v2_retrieval_filters_out_disallowed_permission_tags`. |
| `VR-08-002` | Empty recall returns no evidence and `RAG_NO_EVIDENCE`. See `tests/test_rag_v2_workflow.py::test_rag_v2_empty_recall_returns_no_evidence_warning`. |
| `VR-08-003` | Document-supported claims require returned `evidence_id` citations. See `src/chatbi/rag_explanation.py` and `tests/test_rag_v2_workflow.py::test_rag_v2_answer_cites_returned_evidence_and_records_trace_events`. |
| `VR-08-004` | Documents over 50,000 characters return a queued job, then worker/service completion succeeds. See `tests/test_rag_v2_workflow.py::test_rag_v2_long_document_is_queued_then_worker_succeeds` and `tests/test_rag_worker.py`. |
| `VR-08-005` | Index job statuses are represented as `queued`, `running`, `succeeded`, and `failed`. See `IndexJobStatus`, `rag_service.py`, and `rag_worker.py`. |
| `FR-08-001` | PostgreSQL document rows are modeled in `RAG_V2_TABLES_SQL`, row mappers, repository, migration, and data model catalog. |
| `FR-08-002` | Chunks include `document_id`, position, text, and token count. See `RagChunk` and `tests/test_rag_v2_workflow.py`. |
| `FR-08-003` | Embedding metadata includes model name, model version, and dimensions. See `EmbeddingMetadata` and `tests/test_rag_postgres_rows.py`. |
| `FR-08-004` | Retrieval filters by time window, business tags, and permission tags before returning evidence. |
| `FR-08-005` | Evidence items include source, snippet, date, and relevance score. |
| `FR-08-006` | Evidence events are written and selected by `trace_id`. See `tests/test_rag_v2_workflow.py` and `tests/test_rag_postgres_repository.py`. |
| `NFR-08-001` | Local benchmark helper supports mock retrieval over configurable chunk counts and reports P95. See `src/chatbi/rag_benchmark.py` and `tests/test_rag_benchmark.py`. |
| `NFR-08-002` | Permission leakage fixture returns only allowed document evidence. |
| `NFR-08-003` | Chunking is deterministic for same text and settings. |
| `NFR-08-004` | Focused pyright checks over RAG v2 source return 0 errors. |

## Acceptance Criteria

| Acceptance Criterion | Verification |
|---|---|
| `AC-08-001` | `build_index_artifacts` creates one document, chunks, embedding metadata, and a succeeded job for a sample release note. |
| `AC-08-002` | Unauthorized permission tags are filtered out before evidence return. |
| `AC-08-003` | Empty recall returns `evidence_list == ()` and `RAG_NO_EVIDENCE`. |
| `AC-08-004` | Evidence items include `evidence_id`, `document_id`, `chunk_id`, `snippet`, `source`, and `relevance_score`. |
| `AC-08-005` | Evidence events can be selected by `trace_id` through in-memory and PostgreSQL-shaped repositories. |

## Test Plan Mapping

| Test Case | Current Verification |
|---|---|
| `TC-08-001` | Focused pyright checks cover RAG contracts, service, repository, worker, benchmark, and tests. |
| `TC-08-002` | `tests/test_rag_v2_workflow.py` verifies indexing sample documents and chunk rows. |
| `TC-08-003` | `tests/test_rag_v2_workflow.py` verifies permission mismatch excludes restricted chunks. |
| `TC-08-004` | `tests/test_rag_v2_workflow.py` verifies empty recall warning and no fabricated evidence. |
| `TC-08-005` | `tests/test_rag_v2_workflow.py` and `tests/test_rag_postgres_repository.py` verify trace-linked evidence events. |
| `TC-08-006` | `tests/test_rag_v2_workflow.py` verifies deterministic chunking. |
| `TC-08-007` | `tests/test_rag_benchmark.py` verifies the benchmark helper shape; full 1,000-chunk timing can be run through `run_retrieval_benchmark(build_mock_rag_service(1000))`. |

## Test Files

| Test file | What it proves |
|---|---|
| `tests/test_rag_v2_workflow.py` | End-to-end indexing, retrieval, empty recall, citation, trace events, long-document queueing |
| `tests/test_rag_worker.py` | Worker task lifecycle for queued RAG index jobs |
| `tests/test_rag_postgres_rows.py` | PostgreSQL DDL and row mapper round trips |
| `tests/test_rag_postgres_repository.py` | PostgreSQL-shaped repository SQL calls and row reads using a fake connection |
| `tests/test_rag_benchmark.py` | Benchmark fixture generation and latency result shape |
| `tests/test_rag_v2_exports.py` | Public `chatbi.rag_v2` facade exports |
| `tests/test_rag_v2_demo.py` | Runnable demo produces answer, evidence id, and evidence event id |
| `tests/test_migrations.py` | Base migration includes RAG v2 schema and tables |
| `tests/test_data_model.py` | Data model catalog includes `rag.*` v2 tables |
| `tests/test_knowledge_store.py`, `tests/test_rag_agent.py` | Legacy v1 RAG remains green |

## Design Notes

The v2 RAG architecture is intentionally layered:

1. `rag.py` is the vocabulary: requests, documents, chunks, jobs, evidence, events, warnings.
2. `rag_indexing.py` is the indexing factory: clean text, chunk text, create metadata.
3. `rag_retrieval.py` is the evidence filter and ranker.
4. `rag_explanation.py` is the speaking rule: cited claims only.
5. `rag_answering.py` is the user-facing use case: search plus explanation plus trace events.
6. `rag_repository.py` is the storage boundary: in-memory now, PostgreSQL-shaped for production.
7. `rag_worker.py` is the async handoff adapter for long indexing jobs.
8. `rag_v2.py` is the public import facade.

In plain terms: one layer defines the nouns, one layer prepares documents, one
layer finds safe evidence, one layer writes a cited explanation, and one layer
stores what happened so the answer can be audited by `trace_id`.

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Focused RAG, migration, and data model tests:

```bash
.venv/bin/python -m pytest \
  tests/test_data_model.py \
  tests/test_migrations.py \
  tests/test_rag_v2_demo.py \
  tests/test_rag_benchmark.py \
  tests/test_rag_v2_exports.py \
  tests/test_rag_worker.py \
  tests/test_rag_postgres_repository.py \
  tests/test_rag_postgres_rows.py \
  tests/test_rag_v2_workflow.py \
  tests/test_knowledge_store.py \
  tests/test_rag_agent.py
```

Recent result:

```text
92 passed
```

Focused source pyright:

```bash
.venv/bin/pyright \
  src/chatbi/data_model.py \
  src/chatbi/migrations.py \
  src/chatbi/rag.py \
  src/chatbi/rag_indexing.py \
  src/chatbi/rag_retrieval.py \
  src/chatbi/rag_repository.py \
  src/chatbi/rag_service.py \
  src/chatbi/rag_explanation.py \
  src/chatbi/rag_answering.py \
  src/chatbi/rag_postgres_rows.py \
  src/chatbi/rag_v2.py \
  src/chatbi/rag_worker.py \
  src/chatbi/rag_benchmark.py
```

Recent result:

```text
0 errors, 0 warnings, 0 informations
```

Runnable demo:

```bash
PYTHONPATH=src .venv/bin/python examples/rag_v2_demo.py
```

Recent output includes:

```text
answer_text=... [ev_doc_demo_release_note_chunk_1]
evidence_ids=ev_doc_demo_release_note_chunk_1
event_ids=rag_evt_trc_demo_rag_v2_1
```
