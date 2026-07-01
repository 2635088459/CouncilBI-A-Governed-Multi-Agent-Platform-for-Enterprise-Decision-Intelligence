# Verification: 09 Analytics and Forecasting

This document records the current machine-verifiable status for `spec/version2/09-analytics-and-forecasting.spec.md`.

## Scope

Verified v2 workflow:

```text
SQL-backed metric rows
  -> AnalyticsRequest
  -> date/value validation
  -> insufficient-data degrade path
  -> rolling z-score anomaly detection
  -> deterministic linear forecast with lower/upper bounds
  -> AnalyticsResult
  -> analytics.results persistence by trace_id
  -> synchronous v2 API
  -> asynchronous analytics worker handoff
  -> orchestrator analytics adapter
  -> frontend API client, state store, props, render model, static demo entry
```

Covered implementation files:

| Area | File |
|---|---|
| Typed analytics contract and deterministic service | `src/chatbi/analytics.py` |
| Data model catalog entry | `src/chatbi/data_model.py` |
| In-memory and PostgreSQL repositories | `src/chatbi/analytics_repository.py` |
| PostgreSQL row mapping and DDL | `src/chatbi/analytics_postgres_rows.py` |
| Async analytics task worker | `src/chatbi/analytics_worker.py` |
| Backend v2 analytics endpoints | `src/chatbi/api/http.py` |
| Orchestrator adapter | `src/chatbi/orchestration/analytics_runner.py` |
| Frontend API client | `src/chatbi/frontend/api_client.py` |
| Frontend analytics state | `src/chatbi/frontend/analytics_state.py` |
| Frontend props/i18n/render integration | `src/chatbi/frontend/component_props.py`, `src/chatbi/frontend/i18n.py`, `src/chatbi/frontend/render_model.py` |
| Static browser prototype entry | `src/chatbi/frontend/static_assets/app.js`, `src/chatbi/frontend/static_assets/styles.css` |

## Requirement Coverage

| Requirement | Verification |
|---|---|
| `FR-09-001` | `tests/test_analytics_service.py::test_invalid_dates_return_analytics_invalid_time_series` verifies invalid dates return `ANALYTICS_INVALID_TIME_SERIES`. |
| `FR-09-002` | `tests/test_analytics_service.py::test_valid_daily_revenue_fixture_returns_forecast_and_persists_by_trace_id` runs anomaly detection for eligible rows and returns the required anomaly field. |
| `FR-09-003` | `tests/test_analytics_service.py::test_forecast_points_keep_bounds_ordered` verifies forecast points are generated for enough historical rows. |
| `FR-09-004` | `tests/test_analytics_service.py::test_two_point_fixture_degrades_to_trend_summary` verifies fewer than 3 rows degrade to trend summary plus `INSUFFICIENT_DATA`. |
| `FR-09-005` | `tests/test_analytics_postgres_rows.py` and `tests/test_migrations.py::test_analytics_v2_tables_sql_creates_spec_v2_result_table` verify method, model version, parameters, and result fields can be persisted. |
| `FR-09-006` | `tests/test_v2_chat_query_http.py::test_v2_analytics_analyze_persists_result_and_result_endpoint_reads_it` verifies frontend-facing output includes anomaly and forecast fields. |
| `NFR-09-001` | `tests/test_analytics_performance.py::test_analytics_over_1000_daily_points_stays_under_local_p95_budget` verifies 1,000 daily points stay under the 6000ms local P95 budget. |
| `NFR-09-002` | `tests/test_analytics_service.py::test_same_fixture_returns_identical_anomaly_dates` verifies deterministic anomaly dates for repeated runs. |
| `NFR-09-003` | Focused pyright checks over `src/chatbi/analytics.py`, analytics worker/frontend files, and related tests report 0 errors. |

## Acceptance Criteria

| Acceptance Criterion | Verification |
|---|---|
| `AC-09-001` | Valid daily revenue fixture returns a result with anomaly and forecast fields and no validation error. |
| `AC-09-002` | Two-point fixture returns `INSUFFICIENT_DATA`, empty anomaly points, and empty forecast points. |
| `AC-09-003` | Forecast fixture checks every point satisfies `lower <= value <= upper`. |
| `AC-09-004` | Repository and API tests read saved analytics records back by `trace_id` with method and model version. |
| `AC-09-005` | Determinism test compares anomaly timestamps from two runs of the same fixture. |

## Test Plan Mapping

| Test Case | Current Verification |
|---|---|
| `TC-09-001` | `.venv/bin/python -m pyright src/chatbi/analytics.py tests/test_analytics_performance.py` |
| `TC-09-002` | `tests/test_analytics_service.py::test_valid_daily_revenue_fixture_returns_forecast_and_persists_by_trace_id` |
| `TC-09-003` | `tests/test_analytics_service.py::test_two_point_fixture_degrades_to_trend_summary` |
| `TC-09-004` | `tests/test_analytics_service.py::test_forecast_points_keep_bounds_ordered` |
| `TC-09-005` | `tests/test_analytics_repository.py`, `tests/test_analytics_postgres_rows.py`, and v2 API result lookup tests |
| `TC-09-006` | `tests/test_analytics_service.py::test_same_fixture_returns_identical_anomaly_dates` |
| `TC-09-007` | `tests/test_analytics_performance.py::test_analytics_over_1000_daily_points_stays_under_local_p95_budget` |

## Integration Coverage

| Layer | Verification |
|---|---|
| Service contract | `tests/test_analytics_service.py` |
| Persistence mapping | `tests/test_analytics_repository.py`, `tests/test_analytics_postgres_rows.py`, `tests/test_migrations.py` |
| Data model catalog | `tests/test_data_model.py::test_analytics_v2_results_table_persists_method_parameters_and_forecasts` |
| Async worker | `tests/test_analytics_worker.py`, `tests/test_worker_handoff.py` |
| Orchestrator adapter | `tests/test_analytics_service_runner.py`, `tests/test_simple_orchestrator.py` |
| Backend API | `tests/test_v2_chat_query_http.py` |
| Frontend API/state/props | `tests/test_frontend_api_client.py`, `tests/test_frontend_analytics_state.py`, `tests/test_frontend_analytics_component_props.py` |
| Frontend app shell/render/static build | `tests/test_frontend_app_shell.py`, `tests/test_frontend_render_model.py`, `tests/test_frontend_build_static.py` |

## Design Notes

In plain terms:

1. `analytics.py` is the teacher's formula sheet. It defines what an analytics request must contain, what a result must contain, how bad input is rejected, and how simple deterministic forecasting works.
2. `analytics_repository.py` is the notebook. The service does not care whether the notebook is memory or PostgreSQL; it only asks to save and load by `trace_id`.
3. `analytics_worker.py` is the after-class assistant. Small jobs can run synchronously through the API, while longer analytics work can be queued and later marked `succeeded`, `failed`, or `timed_out`.
4. `analytics_runner.py` is the translator for the older orchestrator shape. It lets the v2 service feed the existing final answer flow without making the rest of the orchestrator know every analytics detail.
5. Frontend files turn the same result into user-facing state, labels, render regions, and a small static demo panel.

The v2 MVP intentionally uses deterministic in-process math instead of heavy ARIMA/Prophet dependencies. That keeps local tests fast, makes repeated outputs explainable, and satisfies the v2 contract that uncertainty must be explicit through warnings and bounds.

## Known Gaps

| Gap | Reason |
|---|---|
| Real model training and registry | Out of scope for spec v2 section 09. |
| Live PostgreSQL analytics integration test | Row mapping and DDL are covered locally; a live database test can be added when the CI database fixture is standardized. |
| Advanced seasonality and causal inference | Explicitly out of scope for this spec. |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
Date: 2026-07-01
```

Focused analytics test suite:

```bash
.venv/bin/python -m pytest \
  tests/test_analytics_performance.py \
  tests/test_analytics_service.py \
  tests/test_analytics_repository.py \
  tests/test_analytics_worker.py
```

Result:

```text
15 passed in 0.07s
```

Focused static check:

```bash
.venv/bin/python -m pyright src/chatbi/analytics.py tests/test_analytics_performance.py
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Frontend/static continuation check:

```bash
.venv/bin/python -m pytest \
  tests/test_frontend_build_static.py \
  tests/test_frontend_static_bootstrap.py \
  tests/test_frontend_architecture_manifest.py \
  tests/test_frontend_render_model.py
```

Result:

```text
21 passed in 0.16s
```
