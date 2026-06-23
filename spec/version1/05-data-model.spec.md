# Spec: Data Model

## 1. Purpose
Define the business, knowledge, runtime, and governance data models that power the ChatBI platform.

## 2. Scope
In scope:
- Business fact and dimension tables
- Semantic catalog storage
- Vector document storage
- Query history, audit, and trace storage
- Cache and config storage

Out of scope:
- Full DWH layering (ODS/DWD/DWS)
- Enterprise MDM integration

Assumptions:
- Business data is ingested via seed scripts or ETL in MVP.
- One canonical metric definition per metric name.

Constraints:
- Sensitive fields MUST be classified P0/P1/P2 before deployment.
- Large fact tables MUST be partitioned by date.

## 3. Domains
- Business analytics domain
- Semantic governance domain
- Knowledge retrieval domain
- Runtime governance domain
- Config/cache domain

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-05-001 | The data model MUST include orders, refunds, customers, products, regions, web_events, support_tickets, marketing_campaigns. |
| FR-05-002 | Each core metric MUST map to one canonical SQL definition. |
| FR-05-003 | The model MUST store document chunks with source_id, doc_type, publish_time, and embedding vector. |
| FR-05-004 | Every query execution MUST produce a query_history record. |
| FR-05-005 | Every Guardrail decision MUST produce an audit_event record. |
| FR-05-006 | Agent step logs MUST be stored in agent_traces with trace_id linkage. |
| FR-05-007 | Sensitive fields MUST carry a classification tag (P0/P1/P2). |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-05-001 | Core queries on fact tables MUST use partition pruning for date-range scans. |
| NFR-05-002 | Data quality rules (non-null PK, non-negative amounts) MUST be enforceable. |
| NFR-05-003 | P0 fields MUST be inaccessible to query generation; P1 MUST be masked in results. |
| NFR-05-004 | Hot audit/history data MUST be retained for >= 180 days. |

## 6. Core Table Artifacts

Business: orders, refunds, customers, products, regions, web_events, support_tickets, marketing_campaigns

Knowledge: documents, doc_chunks, doc_embeddings

Runtime: query_history, audit_events, agent_traces, eval_runs

## 7. Key Metric Definitions

| Metric | Definition |
|---|---|
| revenue | SUM(orders.order_amount) WHERE status='paid' |
| refund_rate | SUM(refunds.refund_amount) / SUM(orders.order_amount) |
| active_users | COUNT(DISTINCT web_events.customer_id) per day |
| order_count | COUNT(DISTINCT orders.order_id) |

## 8. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-05-001 | revenue metric SQL matches the canonical formula and returns correct results on seed data. |
| AC-05-002 | A query to a P0 field is denied before reaching the database. |
| AC-05-003 | A P1 field value is masked in the returned result. |
| AC-05-004 | Every query execution creates a query_history record with trace_id. |
| AC-05-005 | Date-range query on orders uses partition pruning (explain plan confirms). |

## 9. Test Plan

| ID | Type | Description |
|---|---|---|
| TC-05-001 | Unit | DDL constraints reject null PKs and negative amounts. |
| TC-05-002 | Unit | revenue SQL on seed data matches expected value. |
| TC-05-003 | Integration | P0 field query denied before DB execution. |
| TC-05-004 | Integration | P1 field value masked in query result. |
| TC-05-005 | Integration | query_history record created for each executed query. |
| TC-05-006 | Performance | Date-range query on orders shows partition pruning in EXPLAIN. |

## 10. Traceability Matrix

| Requirement | Acceptance Criterion | Test Case |
|---|---|---|
| FR-05-001 | AC-05-001 | TC-05-002 |
| FR-05-002 | AC-05-001 | TC-05-002 |
| FR-05-004 | AC-05-004 | TC-05-005 |
| FR-05-007 | AC-05-002, AC-05-003 | TC-05-003, TC-05-004 |
| NFR-05-001 | AC-05-005 | TC-05-006 |
| NFR-05-003 | AC-05-002, AC-05-003 | TC-05-003, TC-05-004 |

## 11. Open Questions
- OQ-05-001: PostgreSQL or MySQL as primary OLTP in v1?
- OQ-05-002: HNSW or IVF for vector index?
- OQ-05-003: Object storage or cold DB instance for archive?
