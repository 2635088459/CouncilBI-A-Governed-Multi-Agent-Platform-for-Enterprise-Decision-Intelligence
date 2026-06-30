# Verification: 04 SQL Guardrail and Governance v2

This document records the current machine-verifiable status for
`spec/version2/04-sql-guardrail-and-governance.spec.md`.

## Verified Runtime Slice

```text
GuardrailRequestV2
  -> contract validation for trace_id, user_id, role, sql_text length, semantic_version_id

SQL text
  -> SqlStatementValidator
  -> deny empty SQL, multi-statement SQL, non-SELECT SQL, write operations, injection patterns

validated SELECT SQL
  -> SqlReferenceParser
  -> table names, aliases, referenced fields
  -> SqlObjectAccessPolicy
  -> role/table/field access denial or allow

allowed SQL
  -> RowLimitRewriter
  -> enforced LIMIT <= configured max rows
  -> MaskingPlanGenerator
  -> P1 field masking instructions

legacy guardrail result
  -> GuardrailDecisionV2Builder
  -> sql_hash, rule_hits, masking_plan, structured error payload
  -> GuardrailDecisionAuditRecorder
  -> trace_id, sql_hash, decision, rule_hits, latency_ms

runtime database credential
  -> ReadOnlyDatabaseProbe
  -> write probe must be blocked by database permissions
  -> ReadOnlyQueryExecutor
  -> allowed SELECT runs through CHATBI_READONLY_DATABASE_URL
  -> SimpleOrchestrator
  -> QueryAnswer.table_result can come from read-only database execution
  -> business.revenue_by_month
  -> seeded business read model for live chat query results
  -> RuntimeQueryResultStore
  -> successful chat query stores sql_hash and table_result in runtime.query_results
  -> GET /api/v2/query-results/{trace_id}
  -> replay persisted result without returning plaintext SQL
  -> GET /api/v2/governance/traces/{trace_id}
  -> summarize request, query result, and guardrail evidence
```

Verified SQL guardrail/governance components now include:

- typed `GuardrailRequestV2` and `GuardrailDecisionV2` contracts
- `SqlStatementValidator` for non-SELECT, multi-statement, write operation, and injection-pattern denial
- `SqlReferenceParser` for table aliases and referenced field extraction
- `SqlObjectAccessPolicy` for role/table/field authorization
- `RowLimitRewriter` for missing or excessive `LIMIT` rewrite
- `GuardrailSettings` for configurable max rows and timeout
- `QueryTimeoutPolicy` for runtime SQL timeout denial
- `MaskingPlanGenerator` for P1 field masking instructions
- `GuardrailRuleHitBuilder` for auditable rule hits
- `GuardrailErrorPayloadBuilder` for structured v2 denial errors
- `SqlHasher` for privacy-preserving SQL audit hashes
- legacy and v2 audit recorders
- in-memory and PostgreSQL-shaped v2 audit stores
- read-only database write probe boundary
- read-only query execution boundary for already-governed SELECT SQL
- orchestrator and HTTP default app wiring for read-only query results
- seeded `business.revenue_by_month` read model for live query execution
- runtime query result persistence for successful chat query responses
- v2 runtime query result replay endpoint without plaintext SQL exposure
- v2 governance trace summary endpoint for request/result/guardrail evidence
- v2 guardrail HTTP endpoint behavior for masking and denial
- local P95 latency smoke test over 1000 SQL strings
- pyright coverage for governance policy and decision contract types

## Coverage Matrix

| ID | Status | Verification |
|---|---|---|
| `VR-04-001` | Covered | Non-SELECT and write statements are denied before execution. See `tests/test_sql_validator.py`, `tests/test_simple_guardrail.py`, `tests/test_v2_guardrail.py` |
| `VR-04-002` | Covered | Multi-statement SQL is denied and emits `MULTIPLE_STATEMENTS`. See `tests/test_sql_validator.py`, `tests/test_guardrail_rule_hits.py`, `tests/test_v2_guardrail.py` |
| `VR-04-003` | Covered by probe boundary, executor boundary, orchestrator wiring, and optional live integration | `ReadOnlyDatabaseProbe` expects `CREATE TABLE guardrail_probe(id int)` to fail; `ReadOnlyQueryExecutor` runs SELECT through the read-only URL; orchestrator and default HTTP app can consume its `TableResult`; live chat query reads `business.revenue_by_month` through `chatbi_readonly`. See `tests/test_readonly_database_probe.py`, `tests/test_readonly_query_executor.py`, `tests/test_simple_orchestrator.py`, `tests/test_http_app.py`, `tests/test_readonly_database_integration.py`, `tests/test_readonly_query_executor_integration.py`, `tests/test_chat_query_readonly_postgres_integration.py` |
| `VR-04-004` | Covered | Allowed SQL gets an enforced `LIMIT` and excessive limits are capped. See `tests/test_sql_rewriter.py`, `tests/test_simple_guardrail.py`, `tests/test_v2_guardrail.py` |
| `VR-04-005` | Covered | v2 audit records, query result replay, and governance trace summary store/return `sql_hash` but not plaintext SQL, rewritten SQL, database URL, or password. See `tests/test_v2_guardrail.py`, `tests/test_guardrail_audit_store.py`, `tests/test_v2_chat_query_http.py` |
| `FR-04-001` | Covered | `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, and `TRUNCATE` are denied. See `tests/test_sql_validator.py`, `tests/test_v2_guardrail.py` |
| `FR-04-002` | Covered | Unauthorized tables and fields return object denial. See `tests/test_sql_object_access_policy.py`, `tests/test_simple_guardrail.py`, `tests/test_v2_guardrail.py` |
| `FR-04-003` | Covered | P1 fields generate masking instructions. See `tests/test_masking_plan.py`, `tests/test_v2_guardrail.py`, `tests/test_http_app.py` |
| `FR-04-004` | Covered | Missing `LIMIT` is added, excessive limit is capped. See `tests/test_sql_rewriter.py`, `tests/test_guardrail_settings.py` |
| `FR-04-005` | Covered | Allow and deny decisions write audit records. See `tests/test_guardrail_audit_recorder.py`, `tests/test_v2_guardrail.py`, `tests/test_guardrail_audit_store.py` |
| `FR-04-006` | Covered | Denials use structured v2 error payloads. See `tests/test_guardrail_errors.py`, `tests/test_v2_guardrail.py`, `tests/test_http_app.py` |
| `NFR-04-001` | Covered locally | 1000-string guardrail latency smoke test asserts P95 <= 300ms. See `tests/test_v2_guardrail_latency_smoke.py` |
| `NFR-04-002` | Covered | Dangerous fixture interception rate is covered by parametrized write-operation tests. See `tests/test_sql_validator.py`, `tests/test_v2_guardrail.py` |
| `NFR-04-003` | Covered by optional live PostgreSQL integration | PostgreSQL audit store writes allow and deny rows when `DATABASE_URL` is configured. See `tests/test_guardrail_audit_postgres_integration.py` |
| `NFR-04-004` | Covered | Governance pyright test returns 0 errors. See `tests/test_guardrail_pyright.py` |
| `AC-04-001` | Covered | `DROP TABLE orders` returns deny with `SQL_DENIED_WRITE_OPERATION`. See `tests/test_v2_guardrail.py`, `tests/test_http_app.py` |
| `AC-04-002` | Covered | Restricted fields are denied; P1 fields return masking plan for authorized roles. See `tests/test_simple_guardrail.py`, `tests/test_masking_plan.py`, `tests/test_v2_guardrail.py` |
| `AC-04-003` | Covered | `SELECT * FROM orders` style SQL is rewritten with configured limit. See `tests/test_sql_rewriter.py`, `tests/test_simple_guardrail.py` |
| `AC-04-004` | Covered | v2 audit record includes `trace_id`, `sql_hash`, `decision`, `rule_hits`, and latency; successful chat query results persist `sql_hash` and `table_result` in runtime storage. See `tests/test_guardrail_audit_recorder.py`, `tests/test_guardrail_audit_store.py`, `tests/test_runtime_query_result_store.py` |
| `AC-04-005` | Covered by optional live integration | Runtime read-only DB role write probe fails when live readonly DB URL is configured. See `tests/test_readonly_database_integration.py` |

## Test Map

| Test file | What it proves |
|---|---|
| `tests/test_guardrail_contracts.py` | v2 request/decision contracts, required fields, allow/deny invariants |
| `tests/test_sql_validator.py` | empty SQL, multi-statement SQL, write statements, and structural risk denial |
| `tests/test_sql_reference_parser.py` | table, alias, join, and field extraction |
| `tests/test_sql_object_access_policy.py` | role/table/field authorization and P1 field reporting |
| `tests/test_sql_rewriter.py` | missing limit insertion, excessive limit cap, invalid max rows |
| `tests/test_guardrail_settings.py` | env-driven max rows and timeout settings |
| `tests/test_timeout_policy.py` | runtime timeout allow/deny policy |
| `tests/test_masking_plan.py` | P1 masking plan generation and alias resolution |
| `tests/test_guardrail_rule_hits.py` | rule hit generation for rewrite, masking, object denial, multi-statement, and write denial |
| `tests/test_guardrail_errors.py` | structured v2 error payload mapping |
| `tests/test_sql_hashing.py` | deterministic SHA-256 SQL hashing |
| `tests/test_guardrail_decision_builder.py` | v2 allow/deny decision assembly |
| `tests/test_guardrail_legacy_adapter.py` | v2 request to legacy `QueryRequest` adapter |
| `tests/test_guardrail_audit_recorder.py` | legacy and v2 audit recorder behavior |
| `tests/test_guardrail_audit_store.py` | PostgreSQL-shaped v2 audit schema, inserts, and reads |
| `tests/test_simple_guardrail.py` | legacy guardrail end-to-end behavior and audit replay |
| `tests/test_v2_guardrail.py` | v2 guardrail end-to-end contract behavior |
| `tests/test_http_app.py` | HTTP guardrail endpoint serialization for masking and denial; default chat query app wiring to read-only query rows |
| `tests/test_runtime_query_result_store.py` | runtime session/message/query_result persistence with SQL hash and JSON result payload |
| `tests/test_readonly_database_probe.py` | read-only write probe classification |
| `tests/test_readonly_query_executor.py` | read-only SELECT execution result mapping, row cap, and credential-safe failures |
| `tests/test_readonly_database_integration.py` | optional live read-only DB write failure |
| `tests/test_readonly_query_executor_integration.py` | optional live read-only DB SELECT execution |
| `tests/test_chat_query_readonly_postgres_integration.py` | optional live `/api/v1/chat/query` to read-only PostgreSQL business rows, runtime query result persistence, v2 result replay, and governance trace summary |
| `tests/test_guardrail_audit_postgres_integration.py` | optional live PostgreSQL audit allow/deny writes |
| `tests/test_guardrail_http_postgres_integration.py` | optional live HTTP guardrail endpoint to PostgreSQL audit write |
| `tests/test_v2_guardrail_latency_smoke.py` | local P95 <= 300ms over 1000 SQL strings |
| `tests/test_guardrail_pyright.py` | pyright 0-error check for governance modules |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Focused v2 governance tests:

```bash
.venv/bin/pytest \
  tests/test_timeout_policy.py \
  tests/test_guardrail_audit_recorder.py \
  tests/test_guardrail_settings.py \
  tests/test_guardrail_decision_builder.py \
  tests/test_guardrail_legacy_adapter.py \
  tests/test_sql_hashing.py \
  tests/test_guardrail_errors.py \
  tests/test_guardrail_rule_hits.py \
  tests/test_masking_plan.py \
  tests/test_sql_validator.py \
  tests/test_sql_rewriter.py \
  tests/test_sql_reference_parser.py \
  tests/test_sql_object_access_policy.py \
  tests/test_simple_guardrail.py \
  tests/test_v2_guardrail.py \
  tests/test_guardrail_contracts.py \
  tests/test_guardrail_audit_store.py
```

Recent focused result:

```text
135 passed
```

Governance pyright command exercised by `tests/test_guardrail_pyright.py`:

```bash
.venv/bin/pyright \
  src/chatbi/governance \
  tests/test_guardrail_contracts.py \
  tests/test_v2_guardrail.py \
  tests/test_guardrail_audit_store.py
```

Recent result:

```text
0 errors, 0 warnings, 0 informations
```

Optional live tests:

```bash
docker compose up -d postgres

DATABASE_URL=postgresql://... \
  .venv/bin/python -m chatbi.migrate

DATABASE_URL=postgresql://... \
  .venv/bin/pytest tests/test_guardrail_audit_postgres_integration.py

DATABASE_URL=postgresql://... \
  .venv/bin/pytest tests/test_guardrail_http_postgres_integration.py

CHATBI_READONLY_DATABASE_URL=postgresql://... \
  .venv/bin/pytest tests/test_readonly_database_integration.py

DATABASE_URL=postgresql://... CHATBI_READONLY_DATABASE_URL=postgresql://... \
  .venv/bin/pytest tests/test_readonly_query_executor_integration.py

DATABASE_URL=postgresql://... CHATBI_READONLY_DATABASE_URL=postgresql://... \
  .venv/bin/pytest tests/test_chat_query_readonly_postgres_integration.py
```

Local docker-compose URLs:

```bash
export DATABASE_URL=postgresql://chatbi:chatbi_password@localhost:5432/chatbi
export CHATBI_READONLY_DATABASE_URL=postgresql://chatbi_readonly:chatbi_readonly_password@localhost:5432/chatbi

.venv/bin/python -m chatbi.migrate

.venv/bin/pytest \
  tests/test_guardrail_audit_postgres_integration.py \
  tests/test_guardrail_http_postgres_integration.py \
  tests/test_readonly_database_integration.py \
  tests/test_readonly_query_executor_integration.py \
  tests/test_chat_query_readonly_postgres_integration.py
```

Docker Compose now mounts:

```text
./docker/postgres/init:/docker-entrypoint-initdb.d:ro
```

The init script creates `chatbi_readonly` and grants only `USAGE` on
`business` plus `SELECT` on business tables. It intentionally does not grant
`INSERT`, `UPDATE`, or `DELETE`.

Recent local Docker/PostgreSQL live result:

```text
docker compose postgres: healthy on localhost:5432
python -m chatbi.migrate: Migration 001_base_runtime_foundation succeeded
tests/test_guardrail_audit_postgres_integration.py: 1 passed
tests/test_guardrail_http_postgres_integration.py: 1 passed
tests/test_readonly_database_integration.py: 1 passed
tests/test_readonly_query_executor_integration.py: 1 passed
tests/test_chat_query_readonly_postgres_integration.py: 2 passed
governance trace summary endpoint covered by live result replay flow
confirmed tables: business.revenue_by_month, runtime.query_results, public.query_audit_events, public.sql_rule_hits, public.schema_migrations
```

## Remaining Gaps

- SQL parsing is conservative and regex-based. It covers the project SQL shapes and safety fixtures, but not full SQL dialect AST parsing.
- PostgreSQL audit integration and read-only database probe tests are optional live tests gated by environment variables.
- Native database row-level security and enterprise IAM synchronization remain out of scope for this spec.
- Query optimization beyond safety rewrites remains out of scope.

## Next Recommended Step

Move to one of these implementation slices:

```text
Option A:
  add a real SQL AST parser boundary
  -> keep current conservative validator as fallback
  -> improve table/field extraction for nested queries

Option B:
  wire GuardrailSettings into the HTTP app runtime config
  -> read CHATBI_GUARDRAIL_MAX_ROWS and CHATBI_GUARDRAIL_TIMEOUT_MS
  -> verify endpoint behavior changes with config

Option C:
  add live PostgreSQL audit and readonly probe runbook
  -> document env vars
  -> include expected pass/fail output
```
