# Spec: RAG Retrieval and Evidence

## 1. Purpose
Define the retrieval pipeline that grounds answer explanations in business document evidence.

## 2. Scope
In scope:
- Document ingestion, cleaning, chunking, embedding, indexing
- Online retrieval, reranking, deduplication
- Evidence citation and faithfulness constraints

Out of scope:
- Live internet crawling in v1
- Full multilingual corpus alignment

Assumptions:
- Documents are ingested offline before query time.
- Retrieval is always contextualized by the metric and time range from SQL results.

Constraints:
- Every evidence-backed claim MUST cite at least one source.
- Out-of-permission documents MUST NOT appear in results.

## 3. Document Source Types
Weekly reports, release notes, campaign records, support tickets, incident reports, finance reports

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-08-001 | The RAG pipeline MUST ingest documents and store chunks with metadata (source_id, doc_type, publish_time). |
| FR-08-002 | The retriever MUST support filtering by time window and document type. |
| FR-08-003 | The system MUST apply hybrid retrieval (vector + keyword) to produce candidates. |
| FR-08-004 | Retrieved candidates MUST be reranked before selection. |
| FR-08-005 | The final evidence list MUST deduplicate overlapping chunks from the same document. |
| FR-08-006 | Every claim in the explanation MUST map to at least one evidence_item with citation_anchor. |
| FR-08-007 | When no relevant evidence is found, the system MUST flag the absence explicitly in the output. |
| FR-08-008 | Out-of-permission documents MUST be excluded from retrieval results. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-08-001 | Retrieval latency P95 MUST be <= 1.5s. |
| NFR-08-002 | citation_coverage MUST be >= 95% on the benchmark scenario set. |
| NFR-08-003 | unsupported_claim_rate MUST be <= 2%. |
| NFR-08-004 | Incremental document index updates MUST be supported. |

## 6. Workflow
1. Ingest → clean → chunk → embed → index.
2. At query time: retrieve top-K → filter by metadata → rerank → dedupe → select top evidence.
3. Compose explanation with citations.
4. Attach uncertainty notice if evidence is insufficient.

## 7. Contracts

Input:
```
question, metric_context, time_range, user_role, trace_id
```

Output:
```
evidence_list, explanation_text, confidence, uncertainty, retrieval_stats, trace_id
```

evidence_item fields:
```
source_id, title, publish_time, snippet, relevance_score, citation_anchor
```

## 8. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-08-001 | A why-question returns >= 1 evidence item with a valid citation_anchor. |
| AC-08-002 | A query with no matching documents returns explanation with explicit uncertainty flag. |
| AC-08-003 | An out-of-permission document does not appear in evidence_list. |
| AC-08-004 | Adjacent chunks from the same document are merged before returning. |
| AC-08-005 | Retrieval completes within 1.5s P95 under normal load. |

## 9. Test Plan

| ID | Type | Description |
|---|---|---|
| TC-08-001 | Unit | Chunker produces correct chunk sizes and overlaps. |
| TC-08-002 | Unit | Metadata filter removes chunks outside the time window. |
| TC-08-003 | Integration | Known cause question returns relevant evidence from seeded documents. |
| TC-08-004 | Integration | Zero-hit scenario returns output with uncertainty flag. |
| TC-08-005 | Negative | Restricted document does not appear for unauthorized role. |
| TC-08-006 | Performance | Retrieval pipeline completes in <= 1.5s on benchmark set. |

## 10. Traceability Matrix

| Requirement | Acceptance Criterion | Test Case |
|---|---|---|
| FR-08-001 | AC-08-001 | TC-08-001 |
| FR-08-002 | AC-08-001 | TC-08-002 |
| FR-08-005 | AC-08-004 | TC-08-003 |
| FR-08-006 | AC-08-001 | TC-08-003 |
| FR-08-007 | AC-08-002 | TC-08-004 |
| FR-08-008 | AC-08-003 | TC-08-005 |
| NFR-08-001 | AC-08-005 | TC-08-006 |
| NFR-08-002 | AC-08-001 | TC-08-003 |

## 11. Open Questions
- OQ-08-001: Embedding model selection and refresh cadence?
- OQ-08-002: Cross-encoder reranking in v1?
- OQ-08-003: Human-labeled evidence benchmark for ongoing eval?
