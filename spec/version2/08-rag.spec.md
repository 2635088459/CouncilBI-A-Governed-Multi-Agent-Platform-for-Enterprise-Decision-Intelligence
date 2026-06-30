# Spec v2: RAG Retrieval and Evidence Explanation

Source design:
- [Chinese design](../../system_design/08-rag-design/VERSION2.zh-CN.md)
- [English design](../../system_design/08-rag-design/VERSION2.en.md)

## 1. Purpose
Define a verifiable RAG evidence service that can ingest documents, chunk them, embed them, retrieve permitted evidence, and cite evidence in final answers.

## 2. Scope
In scope:
- Document, chunk, embedding metadata, index job, and evidence event models.
- Worker-based indexing.
- Permission-tag filtering before retrieval results are returned.
- Empty-recall behavior and citation requirements.

Out of scope:
- Live internet crawling.
- Automatic translation.
- Claim generation without cited evidence.

## 3. Typed Inputs and Outputs

### 3.1 IndexDocumentRequest
Required fields:
- `document_id: str`
- `source: str`
- `title: str`
- `document_type: Literal["weekly_report", "release_note", "campaign", "ticket", "incident", "finance_report"]`
- `published_at: datetime`
- `business_tags: list[str]`
- `permission_tags: list[str]`
- `text: str` length 1..500000

### 3.2 EvidenceSearchRequest
Required fields:
- `trace_id: str`
- `query_text: str`
- `time_window: TimeWindow | null`
- `business_tags: list[str]`
- `permission_tags: list[str]`
- `limit: int` where `1 <= limit <= 10`

### 3.3 EvidenceItem
Required fields:
- `evidence_id: str`
- `document_id: str`
- `chunk_id: str`
- `snippet: str`
- `source: str`
- `published_at: datetime`
- `relevance_score: float` where `0.0 <= relevance_score <= 1.0`

## 4. Boundary and Validation Rules
| ID | Rule | Verifier |
|---|---|---|
| VR-08-001 | Documents with permission tags not included in user context MUST NOT be returned. | Security test |
| VR-08-002 | Empty recall MUST return an empty evidence list and warning `RAG_NO_EVIDENCE`; it MUST NOT fabricate evidence. | Negative test |
| VR-08-003 | Final RAG explanation MUST cite at least one `evidence_id` when making a document-supported claim. | Contract test |
| VR-08-004 | Indexing MUST be asynchronous for documents over 50,000 characters. | Worker test |
| VR-08-005 | Index jobs MUST record status `queued`, `running`, `succeeded`, or `failed`. | State test |

## 5. Functional Requirements
| ID | Requirement |
|---|---|
| FR-08-001 | RAG indexer MUST create document metadata rows in PostgreSQL. |
| FR-08-002 | RAG indexer MUST create chunks with `document_id`, position, text, and token count. |
| FR-08-003 | RAG indexer MUST store embedding metadata with model name and version. |
| FR-08-004 | Retriever MUST filter by time window, business tags, and permission tags before returning evidence. |
| FR-08-005 | Retriever MUST return evidence items with source, snippet, date, and relevance score. |
| FR-08-006 | Evidence events MUST be written with `trace_id` for returned evidence. |

## 6. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-08-001 | Retrieval over 1,000 chunks with mock embeddings MUST respond P95 <= 1500ms locally. |
| NFR-08-002 | Permission-filter leakage rate MUST be 0 across the permission fixture. |
| NFR-08-003 | Chunking MUST be deterministic for the same document text and chunk settings. |
| NFR-08-004 | Pyright MUST report 0 errors for RAG data and retrieval contracts. |

## 7. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-08-001 | Indexing a sample release note creates one document row and at least one chunk row. |
| AC-08-002 | Retrieval returns only chunks whose permission tags are allowed for the user. |
| AC-08-003 | Empty recall returns `evidence_list == []` and warning `RAG_NO_EVIDENCE`. |
| AC-08-004 | Returned evidence items include `evidence_id`, `document_id`, `chunk_id`, `snippet`, `source`, and `relevance_score`. |
| AC-08-005 | Evidence events can be selected by `trace_id`. |

## 8. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-08-001 | pyright | Validate index and evidence contract types. |
| TC-08-002 | pytest worker | Index sample document and assert document/chunk rows. |
| TC-08-003 | pytest security | Permission mismatch returns no restricted chunks. |
| TC-08-004 | pytest negative | Empty recall returns warning and no fabricated evidence. |
| TC-08-005 | pytest integration | Returned evidence writes evidence events by trace id. |
| TC-08-006 | pytest determinism | Chunk same document twice and compare chunk boundaries. |
| TC-08-007 | benchmark | Retrieval P95 over 1,000 chunks with mock embeddings. |

## 9. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-08-001 | AC-08-001 | TC-08-002 |
| FR-08-002 | AC-08-001 | TC-08-002 |
| FR-08-003 | AC-08-001 | TC-08-002 |
| FR-08-004 | AC-08-002 | TC-08-003 |
| FR-08-005 | AC-08-004 | TC-08-004 |
| FR-08-006 | AC-08-005 | TC-08-005 |
| NFR-08-001 | AC-08-004 | TC-08-007 |
| NFR-08-002 | AC-08-002 | TC-08-003 |
| NFR-08-003 | AC-08-001 | TC-08-006 |
| NFR-08-004 | AC-08-001 | TC-08-001 |

## 10. First Red-Green Steps
1. Define document and evidence models.
2. Implement deterministic chunking for one sample document.
3. Add permission filter before retrieval.
4. Add empty-recall warning behavior.

