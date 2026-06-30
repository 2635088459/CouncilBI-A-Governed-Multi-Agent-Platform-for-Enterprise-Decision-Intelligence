# Verification: 03 Semantic Layer and NL2SQL v2

This document records the current machine-verifiable status for
`spec/version2/03-semantic-layer-and-nl2sql.spec.md`.

## Verified Runtime Slice

```text
SemanticResolveRequest
  -> validation for trace_id, user_id, role, question length, locale

PostgreSQL semantic catalog rows
  -> PostgresSemanticCatalogStore
  -> SemanticCatalog
  -> MetricDefinition
  -> canonical metric id, formula, owner, status, semantic_version_id

business question
  -> QuestionParser
  -> canonical metric
  -> time range
  -> day/month grain
  -> SemanticResolveResponse

resolved semantic question
  -> SqlTemplateGenerator
  -> SqlPreviewResponse(executes=false)
  -> semantic_version_id
  -> SimpleSqlGuardrail

ambiguous or unauthorized question
  -> needs_clarification or permission_denied
  -> no SQL preview generated

schema snapshots
  -> SchemaDriftDetector
  -> changed fields report
```

Verified semantic/NL2SQL components now include:

- typed `SemanticResolveRequest` with v2 role and locale validation
- `SemanticResolveResponse` with resolved metrics, dimensions, time range, filters, status, and clarification
- non-executing `SqlPreviewResponse` with stable SQL hash and `semantic_version_id`
- governed `MetricDefinition` metadata: `metric_id`, `formula`, `owner`, `status`, and `semantic_version_id`
- PostgreSQL-shaped `PostgresSemanticCatalogStore` for loading metric catalog rows from `semantic.metrics`
- `/api/v1/metrics/catalog` response fields required by v2 catalog acceptance
- seeded `revenue` metric and `order_month` dimension through migration SQL
- benchmark question resolution for `show monthly revenue for 2024`
- high-sensitivity field denial before SQL generation
- ambiguous metric clarification with no SQL generation
- schema drift detection for added, removed, type-changed, and sensitivity-changed fields
- deterministic resolver behavior over 20 repeated benchmark runs
- semantic pyright coverage for catalog, request contract, catalog store, schema drift, and SQL preview-related modules

## Coverage Matrix

| ID | Status | Verification |
|---|---|---|
| `VR-03-001` | Covered | SQL generation uses `ParsedQuestion.metric` and month/day dimension ids from semantic resolution. See `tests/test_sql_generator.py`, `tests/test_semantic_pipeline.py` |
| `VR-03-002` | Covered | Ambiguous shared alias returns `needs_clarification`, one clarification question, and no SQL. See `tests/test_semantic_catalog.py`, `tests/test_semantic_pipeline.py` |
| `VR-03-003` | Covered for high-sensitivity field denial | `customer id` resolves to high-sensitivity `user_id`, returns `permission_denied`, and no SQL. See `tests/test_semantic_pipeline.py`, SQL preview endpoint tests in `tests/test_http_app.py` |
| `VR-03-004` | Covered by preview contract boundary | `SqlPreviewResponse.executes` is always `False`; preview endpoint returns no SQL for denial/clarification. See `tests/test_sql_generator.py`, `tests/test_http_app.py` |
| `VR-03-005` | Covered | SQL preview includes `semantic_version_id` and stable hash. See `tests/test_sql_generator.py`, `tests/test_semantic_pipeline.py`, `tests/test_http_app.py` |
| `FR-03-001` | Covered by PostgreSQL-shaped adapter | `PostgresSemanticCatalogStore` loads rows from `semantic.metrics` by semantic version. See `tests/test_semantic_catalog_store.py` |
| `FR-03-002` | Covered | `GET /api/v1/metrics/catalog` returns metric definitions. See `tests/test_http_app.py` |
| `FR-03-003` | Covered | Benchmark question resolves `revenue` and grain `month`. See `tests/test_question_parser.py`, `tests/test_semantic_pipeline.py` |
| `FR-03-004` | Covered locally | SQL generator uses catalog-defined metric table/expression and guardrail validates output. See `tests/test_sql_generator.py`, `tests/test_semantic_pipeline.py` |
| `FR-03-005` | Covered | `SchemaDriftDetector` emits changed fields for added, removed, data type changed, and sensitivity changed fields. See `tests/test_schema_drift.py` |
| `FR-03-006` | Covered | Migration SQL creates semantic tables and seeds `revenue` plus `order_month`. See `tests/test_migrations.py` |
| `NFR-03-001` | Covered as local payload smoke | 100-metric catalog payload P95 stays under 200ms locally. See `tests/test_metrics_catalog_performance.py` |
| `NFR-03-002` | Covered | Same benchmark input repeated 20 times returns identical metric id, dimension grain, and SQL hash. See `tests/test_semantic_pipeline.py` |
| `NFR-03-003` | Covered | Semantic pyright test returns 0 errors. See `tests/test_semantic_pyright.py` |
| `AC-03-001` | Covered | Catalog API returns `revenue` with id, formula, owner, status, and semantic version id. See `tests/test_http_app.py` |
| `AC-03-002` | Covered | `show monthly revenue for 2024` resolves metric `revenue` and grain `month`. See `tests/test_semantic_pipeline.py` |
| `AC-03-003` | Covered for restricted field | High-sensitivity field request returns `permission_denied` and no SQL. See `tests/test_semantic_pipeline.py`, `tests/test_http_app.py` |
| `AC-03-004` | Covered | Ambiguous metric phrase returns one clarification question and no SQL. See `tests/test_semantic_pipeline.py` |
| `AC-03-005` | Covered by contract; real executor not wired into preview | Preview returns `executes == false`; current preview pipeline has no executor dependency to call. See `tests/test_sql_generator.py`, `tests/test_http_app.py` |

## Test Map

| Test file | What it proves |
|---|---|
| `tests/test_semantic_contracts.py` | v2 `SemanticResolveRequest` required fields, role, locale, and question length validation |
| `tests/test_semantic_catalog.py` | canonical revenue metric, synonyms, ambiguity, version increment enforcement, owner/status/formula metadata |
| `tests/test_semantic_catalog_store.py` | PostgreSQL-shaped semantic metric loading from `semantic.metrics` |
| `tests/test_question_parser.py` | metric extraction, month grain, explicit year range, ambiguity, high-sensitivity field parsing |
| `tests/test_sql_generator.py` | deterministic SQL preview text, hash, explanation, semantic version, and non-execution flag |
| `tests/test_semantic_pipeline.py` | NL2SQL pipeline, semantic response statuses, guardrail handoff, clarification, permission denial, 20-run determinism |
| `tests/test_http_app.py` | `/api/v1/metrics/catalog` and `/api/v1/sql/preview` endpoint behavior |
| `tests/test_schema_drift.py` | schema snapshot comparison and changed field emission |
| `tests/test_migrations.py` | semantic catalog tables and reproducible revenue seed SQL |
| `tests/test_metrics_catalog_performance.py` | local 100-metric catalog payload P95 budget |
| `tests/test_semantic_pyright.py` | pyright 0-error check for semantic contracts and catalog modules |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Focused v2 semantic tests:

```bash
.venv/bin/pytest \
  tests/test_semantic_catalog.py \
  tests/test_semantic_catalog_store.py \
  tests/test_schema_drift.py \
  tests/test_semantic_contracts.py \
  tests/test_semantic_pipeline.py \
  tests/test_http_app.py::test_metrics_catalog_endpoint_returns_metric_definitions \
  tests/test_migrations.py \
  tests/test_metrics_catalog_performance.py \
  tests/test_semantic_pyright.py
```

Recent focused result:

```text
40 passed, 1 warning
```

Semantic pyright command exercised by `tests/test_semantic_pyright.py`:

```bash
.venv/bin/pyright \
  src/chatbi/semantic \
  tests/test_semantic_contracts.py \
  tests/test_semantic_catalog_store.py \
  tests/test_schema_drift.py
```

Recent result:

```text
0 errors, 0 warnings, 0 informations
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient
```

This warning comes from the third-party FastAPI/TestClient stack and does not
indicate a failing project test.

## Remaining Gaps

The following items are represented by local or adapter boundaries in this slice:

- `FR-03-001`: `PostgresSemanticCatalogStore` has a PostgreSQL-shaped connection boundary and SQL query test, but no live PostgreSQL integration test for semantic catalog rows yet.
- `NFR-03-001`: the current performance check measures local catalog payload construction for 100 metrics, not a live PostgreSQL-backed API with 100 metrics and 200 dimensions.
- `AC-03-005`: SQL preview has no executor dependency and returns `executes == false`; a literal mock executor call-count assertion can be added once the preview route accepts an executor boundary.
- Restricted access is currently modeled through high-sensitivity field denial; metric-level role authorization can be expanded when the catalog has role policy columns.

## Next Recommended Step

Move to one of these implementation slices:

```text
Option A:
  add live PostgreSQL semantic catalog integration test
  -> run semantic seed SQL
  -> load revenue through PostgresSemanticCatalogStore

Option B:
  add metric-level role policy columns
  -> deny restricted metrics by role
  -> keep no-SQL permission_denied behavior

Option C:
  expose executor boundary to SQL preview tests
  -> assert executes=false
  -> assert executor call count remains 0
```
