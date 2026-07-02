# Spec FV-03: Embedding and Vector RAG

Source design:
- [Embedding and Vector RAG design](../../../system_design/final-version/en/04-embedding-vector-rag.en.md)
- [Final roadmap](../../../system_design/final-version/en/09-final-delivery-roadmap.en.md)

## 1. Purpose
Define real document ingestion, embedding, vector storage, tenant-filtered retrieval, and citation-grounded RAG behavior.

## 2. Scope
In scope:
- Document parsing metadata, chunking, embedding, vector storage, search, rerank hook, context builder, citations.
- Tenant and permission filtering for every retrieval path.
- Mock embedding provider and vector store for deterministic tests.

Out of scope:
- Full document editor or enterprise content management system.
- Vendor-specific vector-store lock-in.

## 3. Functional Requirements
| ID | Requirement |
|---|---|
| FR-FV03-001 | The system MUST define `EmbeddingClient` and `VectorStore` abstractions. |
| FR-FV03-002 | The system MUST support deterministic mock embeddings for tests. |
| FR-FV03-003 | Documents MUST be stored with `document_id`, `org_id`, source metadata, version, and access policy. |
| FR-FV03-004 | Chunks MUST store `chunk_id`, `document_id`, `org_id`, text, token count, and vector reference. |
| FR-FV03-005 | Query retrieval MUST filter by tenant before returning evidence. |
| FR-FV03-006 | RAG answers MUST include citations for used evidence chunks. |
| FR-FV03-007 | If evidence is insufficient, the system MUST return a missing-evidence warning instead of inventing facts. |
| FR-FV03-008 | Embedding cost and latency MUST be observable. |

## 4. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-FV03-001 | Vector search over 10,000 mock chunks SHOULD complete P95 <= 500ms locally. |
| NFR-FV03-002 | Retrieval MUST be deterministic in tests with mock embeddings. |
| NFR-FV03-003 | Chunk size MUST be bounded to control prompt token usage. |
| NFR-FV03-004 | Deleted or disabled documents MUST not be retrieved. |

## 5. Contracts
### 5.1 DocumentRecord
- `document_id: str`
- `org_id: str`
- `title: str`
- `source_type: str`
- `owner_user_id: str`
- `version: str`
- `access_policy: dict`
- `status: Literal["active", "deleted", "disabled"]`

### 5.2 EvidenceChunk
- `chunk_id: str`
- `document_id: str`
- `org_id: str`
- `text: str`
- `score: float`
- `citation: dict`

## 6. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-FV03-001 | Seeded or uploaded documents can be chunked, embedded, stored, and searched. |
| AC-FV03-002 | Tenant A cannot retrieve Tenant B document chunks. |
| AC-FV03-003 | RAG response includes citations for every evidence-backed claim. |
| AC-FV03-004 | Missing evidence returns a warning and does not fabricate citations. |
| AC-FV03-005 | Embedding and search events include trace id, org id, latency, and provider metadata. |

## 7. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-FV03-001 | unit | Chunker preserves document id, org id, section, and token count. |
| TC-FV03-002 | unit | Mock embedding provider returns stable vectors. |
| TC-FV03-003 | integration | Ingest document, embed chunks, search by question, return evidence. |
| TC-FV03-004 | integration negative | Tenant A search cannot return Tenant B chunks. |
| TC-FV03-005 | integration negative | Deleted document chunks are excluded. |
| TC-FV03-006 | response | RAG answer contains citations matching returned chunks. |
| TC-FV03-007 | response negative | No evidence returns missing-evidence warning. |
| TC-FV03-008 | benchmark | Vector search P95 over 10,000 mock chunks. |

## 8. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-FV03-001 | AC-FV03-001 | TC-FV03-003 |
| FR-FV03-002 | AC-FV03-001 | TC-FV03-002 |
| FR-FV03-003 | AC-FV03-001 | TC-FV03-001 |
| FR-FV03-004 | AC-FV03-001 | TC-FV03-001 |
| FR-FV03-005 | AC-FV03-002 | TC-FV03-004 |
| FR-FV03-006 | AC-FV03-003 | TC-FV03-006 |
| FR-FV03-007 | AC-FV03-004 | TC-FV03-007 |
| FR-FV03-008 | AC-FV03-005 | TC-FV03-003 |

