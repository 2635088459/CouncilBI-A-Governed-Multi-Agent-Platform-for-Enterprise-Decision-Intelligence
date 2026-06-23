# Verification: 05 Data Model

This document records the current machine-verifiable status for the MVP implementation slice based on `spec/version1/05-data-model.spec.md`.

## Scope

Verified workflows:

```text
data model metadata
  -> DataModelCatalog
  -> business, semantic, knowledge, runtime, and config/cache table definitions
  -> primary keys, foreign keys, partition columns, retention days, sensitivity tags

core metric definitions
  -> DataModelCatalog metric registry
  -> MetricEvaluator
  -> canonical SQL definition lookup
  -> seed-row metric calculation

data quality rules
  -> table quality_rules
  -> DataQualityValidator
  -> non-null primary key, non-negative amount, and partition-column checks

sensitive field governance
  -> P0/P1 classification in DataModelCatalog
  -> SimpleSqlGuardrail denies P0 field access
  -> PiiResultMasker masks P1 result fields

runtime governance records
  -> QueryHistoryRecord
  -> InMemoryQueryHistory
  -> GuardrailAuditRecord / InMemoryGuardrailAuditLog
  -> AgentTraceEvent / InMemoryAgentTraceLog
  -> trace_id linkage across history, audit, and agent traces

partition pruning guard
  -> PartitionPruningChecker
  -> generated revenue SQL
  -> orders.order_date lower and upper bound checks

knowledge retrieval model
  -> KnowledgeDocument
  -> DocumentChunk
  -> ChunkEmbedding
  -> InMemoryKnowledgeStore
  -> RagAgentRunner
  -> SimpleOrchestrator evidence_list
```

This slice verifies the data-model metadata, executable data quality checks, canonical metrics on seed rows, P0/P1 governance integration, in-memory runtime governance stores, partition-filter checks for generated SQL, and an in-memory knowledge store feeding RAG evidence.

It does not yet create real database DDL, run real database constraints, run a physical `EXPLAIN` plan, or build a real vector index.

## Covered Requirements

| Requirement | Verification |
|---|---|
| `FR-05-001` | `tests/test_data_model.py` verifies the required business tables: orders, refunds, customers, products, regions, web_events, support_tickets, marketing_campaigns |
| `FR-05-002` | `tests/test_data_model.py` verifies canonical metric definitions; `tests/test_metrics.py` verifies metric lookup and seed-row evaluation |
| `FR-05-003` | `tests/test_data_model.py` verifies documents/doc_chunks/doc_embeddings metadata; `tests/test_knowledge_store.py` verifies source_id, doc_type, publish_time, chunk, and embedding storage |
| `FR-05-004` | `tests/test_simple_orchestrator.py`, `tests/test_in_memory_history.py`, and `tests/test_app.py` verify query_history records by trace_id |
| `FR-05-005` | `tests/test_simple_guardrail.py` verifies guardrail audit records, audit_event_id generation, and multiple audit events per trace_id |
| `FR-05-006` | `tests/test_agent_step_tracing.py` verifies agent_trace_id and trace_id-linked agent step events |
| `FR-05-007` | `tests/test_data_model.py` verifies P0/P1 sensitivity tags; `tests/test_simple_guardrail.py` and `tests/test_pii_masking.py` verify governance behavior based on those tags |
| `NFR-05-001` | `tests/test_partitioning.py` verifies generated orders SQL includes partition-column lower and upper bounds |
| `NFR-05-002` | `tests/test_data_quality.py` verifies executable quality rules for non-null primary keys, non-negative amounts, and required partition columns |
| `NFR-05-003` | `tests/test_simple_guardrail.py` verifies P0 denial; `tests/test_pii_masking.py` verifies P1 result masking |
| `NFR-05-004` | `tests/test_data_model.py` verifies 180-day retention metadata for query_history and audit_events |

## Acceptance Criteria

| Acceptance Criterion | Verification |
|---|---|
| `AC-05-001` | `tests/test_metrics.py` verifies `revenue` canonical SQL and computes paid-order revenue on seed rows |
| `AC-05-002` | `tests/test_simple_guardrail.py` verifies P0 fields such as `customers.customer_id` and `orders.customer_id` are denied before execution |
| `AC-05-003` | `tests/test_pii_masking.py` verifies P1 fields such as `user_email`, `phone`, and `customer_name` are masked in results |
| `AC-05-004` | `tests/test_simple_orchestrator.py` and `tests/test_in_memory_history.py` verify query_history records with trace_id |
| `AC-05-005` | `tests/test_partitioning.py` verifies generated revenue SQL filters `orders.order_date` with lower and upper bounds; physical `EXPLAIN` remains future work |

## Test Plan Mapping

| Test Case | Current Verification |
|---|---|
| `TC-05-001` | `tests/test_data_quality.py` covers null primary key and negative amount failures at the row-validation layer |
| `TC-05-002` | `tests/test_metrics.py` covers revenue SQL definition and seed-row expected revenue |
| `TC-05-003` | `tests/test_simple_guardrail.py` covers P0 field denial before database execution |
| `TC-05-004` | `tests/test_pii_masking.py` covers P1 masking in returned table results |
| `TC-05-005` | `tests/test_simple_orchestrator.py`, `tests/test_in_memory_history.py`, and `tests/test_app.py` cover query_history creation |
| `TC-05-006` | `tests/test_partitioning.py` covers partition-filter SQL checks; physical EXPLAIN is not implemented in the MVP |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Layer 1 static check:

```bash
.venv/bin/pyright
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Layer 2 test suite:

```bash
.venv/bin/python -m pytest
```

Result:

```text
170 passed, 1 warning
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient
```

This warning comes from the third-party FastAPI/TestClient stack and does not indicate a failing project test.

## MVP Notes

The current slice is intentionally metadata-first and in-memory:

- Table definitions are Python metadata, not emitted database DDL.
- Data quality checks run on row-like dictionaries, not real database constraints.
- Partition pruning is verified by SQL shape checks, not physical database `EXPLAIN`.
- Knowledge storage is in-memory and supports metadata filtering, but not vector similarity search.
- Metrics are evaluated against seed-row data, not pushed down into an OLTP or warehouse engine.

## Next Slice

Recommended next implementation slice:

```text
06 Backend API
  -> expose current orchestrator workflow through API models
  -> decide which in-memory stores become request-scoped, app-scoped, or database-backed
  -> prepare persistence boundaries for query_history, audit_events, agent_traces, and knowledge records
```

If the project wants to deepen spec 05 first, the next data-model step should be:

```text
DDL generation
  -> DataModelCatalog
  -> PostgreSQL-compatible CREATE TABLE statements
  -> unit tests for primary keys, foreign keys, partition columns, and retention metadata
```
