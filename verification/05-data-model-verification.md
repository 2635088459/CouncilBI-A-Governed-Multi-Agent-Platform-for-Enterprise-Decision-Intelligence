# Verification: 05 Data Model

This document records the current machine-verifiable status for `spec/version2/05-data-model.spec.md`.

## Scope

Verified workflows:

```text
v2 PostgreSQL migration foundation
  -> schema_migrations metadata
  -> business, semantic, runtime, governance, evaluation, knowledge schemas
  -> runtime.sessions, runtime.messages, runtime.query_history, runtime.query_results, runtime.agent_traces
  -> semantic.semantic_versions, semantic.metrics, semantic.dimensions
  -> knowledge.documents, knowledge.doc_chunks, knowledge.doc_embeddings metadata
  -> governance.access_policies, query_audit_events, sql_rule_hits
  -> evaluation.eval_cases, evaluation.eval_runs, evaluation.eval_scores

seed reproducibility
  -> revenue KPI fixture
  -> anomaly/RAG policy document fixture
  -> restricted P0 field policy fixture
  -> completed demo query fixture using trace_id trc_demo_revenue_2026_h1

trace-based replay
  -> DEMO_TRACE_JOIN_SQL
  -> TraceLinkedRecord / TraceLinkedRecordType
  -> build_trace_linked_records
  -> PostgresTraceLinkedRecordStore

runtime query history persistence
  -> RuntimeQueryHistoryRecord
  -> PostgresRuntimeQueryHistoryStore
  -> get(trace_id)
  -> list_by_session(session_id, limit)
  -> session_id + created_at lookup index metadata
  -> optional live PostgreSQL 10,000-row session lookup benchmark

metadata alignment
  -> DataModelCatalog query_history metadata matches migration fields
  -> final_answer is modeled as durable runtime data
  -> session and status lookup indexes are represented in metadata
```

## Covered Requirements

| Requirement | Verification |
|---|---|
| `FR-05-001` | `tests/test_migrations.py` verifies all six v2 schemas are emitted by migration SQL. |
| `FR-05-002` | `tests/test_migrations.py` verifies `runtime.sessions`, `runtime.messages`, `runtime.query_history`, `runtime.query_results`, and `runtime.agent_traces`. |
| `FR-05-003` | `tests/test_migrations.py` verifies `semantic.semantic_versions`, `semantic.metrics`, and `semantic.dimensions`; `tests/test_data_model.py` verifies semantic metadata. |
| `FR-05-004` | `tests/test_migrations.py` verifies `knowledge.documents`, `knowledge.doc_chunks`, and `knowledge.doc_embeddings` metadata and seed data. |
| `FR-05-005` | `tests/test_migrations.py` verifies the completed demo query seed across runtime, audit, and evaluation tables. |
| `FR-05-006` | `tests/test_migrations.py`, `tests/test_trace_linked_record_store.py`, and `tests/test_overall_architecture.py` verify trace-linked join contracts. |
| `NFR-05-002` | `tests/test_migrations.py`, `tests/test_data_model.py`, and `tests/test_runtime_query_history_store.py` verify the session_id + created_at lookup path. `tests/test_data_model_query_history_benchmark.py` seeds 10,000 live PostgreSQL rows and verifies the recent-history lookup when `DATABASE_URL` is available. |
| `NFR-05-003` | `tests/test_migrations.py` verifies required indexes and the unique `runtime.query_results.trace_id` constraint. |
| `NFR-05-004` | Pyright passes for data model and repository files listed below. |

## Acceptance Criteria

| Acceptance Criterion | Verification |
|---|---|
| `AC-05-001` | `tests/test_migrations.py` verifies schemas `business`, `semantic`, `runtime`, `governance`, `evaluation`, and `knowledge`. |
| `AC-05-002` | `tests/test_migrations.py` verifies seed metric `revenue`, one session, one RAG document, and one restricted field policy. |
| `AC-05-003` | `tests/test_migrations.py` verifies `runtime.query_results.trace_id` is unique. `tests/test_data_model_postgres_integration.py` performs the physical duplicate insert check when `DATABASE_URL` is available. |
| `AC-05-004` | `DEMO_TRACE_JOIN_SQL` and `PostgresTraceLinkedRecordStore` verify one demo query can join message, query_result, agent_trace, audit_event, and eval_score by trace id. |
| `AC-05-005` | `runtime.query_history` has `idx_runtime_query_history_session_created_at`; `PostgresRuntimeQueryHistoryStore.list_by_session` uses `WHERE session_id`, `ORDER BY created_at DESC`, and `LIMIT`. `tests/test_data_model_query_history_benchmark.py` performs live `EXPLAIN` plus 10,000-row lookup verification when `DATABASE_URL` is available. |

## Test Plan Mapping

| Test Case | Current Verification |
|---|---|
| `TC-05-001` | Pyright validates `src/chatbi/data_model.py`, `src/chatbi/migrations.py`, `src/chatbi/history/query_history.py`, and `src/chatbi/history/trace_links.py`. |
| `TC-05-002` | `tests/test_migrations.py` verifies migration SQL can create the v2 schema surface from a blank database shape. |
| `TC-05-003` | `tests/test_migrations.py` verifies KPI, RAG, permission, evaluation, and completed query fixtures. |
| `TC-05-004` | `tests/test_migrations.py` verifies the unique trace constraint declaration; `tests/test_data_model_postgres_integration.py` performs the physical duplicate insert check when `DATABASE_URL` is available. |
| `TC-05-005` | `tests/test_trace_linked_record_store.py` verifies joined trace rows become typed `TraceLinkedRecord` objects. |
| `TC-05-006` | `tests/test_runtime_query_history_store.py` verifies the session history query shape; `tests/test_data_model_query_history_benchmark.py` verifies the physical 10,000-row lookup path when `DATABASE_URL` is available. |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Focused test suite:

```bash
.venv/bin/python -m pytest tests/test_data_model.py tests/test_migrations.py tests/test_runtime_query_history_store.py
```

Result:

```text
55 passed
```

Additional repository/contract tests:

```bash
.venv/bin/python -m pytest tests/test_runtime_query_history_store.py tests/test_migrations.py tests/test_trace_linked_record_store.py
```

Result:

```text
42 passed
```

Focused suite including live PostgreSQL integration hook:

```bash
.venv/bin/python -m pytest tests/test_data_model_query_history_benchmark.py tests/test_data_model_postgres_integration.py tests/test_data_model.py tests/test_migrations.py tests/test_runtime_query_history_store.py tests/test_trace_linked_record_store.py
```

Result in the current local shell:

```text
58 passed, 2 skipped
```

Skipped test:

```text
tests/test_data_model_postgres_integration.py requires DATABASE_URL.
tests/test_data_model_query_history_benchmark.py requires DATABASE_URL.
```

Static checks:

```bash
.venv/bin/pyright src/chatbi/data_model.py tests/test_data_model.py
.venv/bin/pyright src/chatbi/history/query_history.py tests/test_runtime_query_history_store.py
.venv/bin/pyright src/chatbi/migrations.py tests/test_migrations.py src/chatbi/history/trace_links.py tests/test_trace_linked_record_store.py
.venv/bin/pyright tests/test_data_model_query_history_benchmark.py tests/test_data_model_postgres_integration.py src/chatbi/history/query_history.py src/chatbi/migrations.py
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

## Remaining Work

- Run the base migration against a real blank PostgreSQL database in CI.
- Run `tests/test_data_model_postgres_integration.py` and `tests/test_data_model_query_history_benchmark.py` with `DATABASE_URL` in CI to exercise the physical PostgreSQL checks.
- Keep `query_audit_events` and `sql_rule_hits` unqualified for now so spec 5 stays compatible with the existing governance audit repositories from spec 4.
