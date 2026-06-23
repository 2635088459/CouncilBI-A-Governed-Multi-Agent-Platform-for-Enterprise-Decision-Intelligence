# Verification: 09 Analytics and Forecasting

This document records the current machine-verifiable status for `spec/version1/09-analytics-and-forecasting.spec.md`.

## Scope

Verified workflow:

```text
SQL-style revenue time series
  -> TimeSeriesPoint normalization
  -> data quality check
  -> anomaly detection with Bollinger-style rolling z-score
  -> deterministic forecast
  -> moving-average fallback on model fit failure
  -> confidence interval bounds
  -> fact / judgment / uncertainty narrative
  -> model_run metadata
  -> SimpleOrchestrator analytics_result
  -> Backend API response
  -> Frontend QueryResultViewModel
  -> ChatPageProps AnalyticsInsightProps
```

Covered implementation files:

| Area | File |
|---|---|
| Analytics agent and time-series logic | `src/chatbi/agents/analytics_agent.py` |
| Forecast task routing | `src/chatbi/orchestration/routing.py` |
| Orchestrator integration | `src/chatbi/orchestration/simple_orchestrator.py` |
| Core answer contract | `src/chatbi/core/contracts.py` |
| API response mapping | `src/chatbi/api/models.py` |
| Frontend analytics view model | `src/chatbi/frontend/view_models.py` |
| Frontend analytics component props | `src/chatbi/frontend/component_props.py` |
| Frontend analytics i18n labels | `src/chatbi/frontend/i18n.py` |

## Covered Requirements

| Requirement | Verification |
|---|---|
| `FR-09-001` | `tests/test_analytics_agent.py::test_analytics_agent_empty_series_returns_quality_error_not_model_crash` verifies data quality runs before modeling and returns a controlled result instead of crashing |
| `FR-09-002` | `tests/test_analytics_agent.py::test_analytics_agent_detects_injected_spike` verifies `anomaly_points`, `anomaly_score`, and `anomaly_level` are returned |
| `FR-09-003` | `tests/test_analytics_agent.py::test_analytics_agent_forecast_includes_bounds_and_model_used` verifies `forecast_series`, `lower_bound`, `upper_bound`, and `model_used` |
| `FR-09-004` | `tests/test_analytics_agent.py::test_analytics_agent_falls_back_to_moving_average_when_fit_fails` verifies moving-average fallback and fallback flag |
| `FR-09-005` | `tests/test_analytics_agent.py::test_analytics_agent_narrative_uses_fact_judgment_uncertainty_sections` verifies narrative sections: fact, judgment, uncertainty |
| `FR-09-006` | `tests/test_analytics_agent.py::test_analytics_agent_forecast_includes_bounds_and_model_used` exercises `model_used`; `model_run` includes `model_version`, requested model, and parameters in `AnalyticsAgentRunner.run` |
| `NFR-09-001` | Full suite and focused analytics tests run well under the 6s target locally; formal P95 benchmark over a defined workload remains future work |
| `NFR-09-002` | The current analytics implementation is deterministic: it uses pure Python arithmetic, fixed windows, no randomness, and no external model server |
| `NFR-09-003` | Per-run fallback warnings are exposed; sustained model failure alerting is not implemented in the MVP |

## Acceptance Criteria

| Acceptance Criterion | Verification |
|---|---|
| `AC-09-001` | `tests/test_analytics_agent.py::test_analytics_agent_detects_injected_spike` verifies an injected spike returns at least one anomaly point with an anomaly level |
| `AC-09-002` | `tests/test_analytics_agent.py::test_analytics_agent_forecast_includes_bounds_and_model_used` verifies forecast bounds and model name |
| `AC-09-003` | `tests/test_analytics_agent.py::test_analytics_agent_falls_back_to_moving_average_when_fit_fails` verifies fallback flag and moving-average result |
| `AC-09-004` | `tests/test_analytics_agent.py::test_analytics_agent_narrative_uses_fact_judgment_uncertainty_sections` verifies all three narrative sections |
| `AC-09-005` | `.venv/bin/python -m pytest` completes locally in under 1 second for the full suite; formal P95 analytics latency benchmark remains future work |

## Test Plan Mapping

| Test Case | Current Verification |
|---|---|
| `TC-09-001` | `tests/test_analytics_agent.py::test_analytics_agent_detects_injected_spike` |
| `TC-09-002` | `tests/test_analytics_agent.py::test_analytics_agent_forecast_includes_bounds_and_model_used`; v1 uses a deterministic trend approximation for Prophet/ARIMA-shaped outputs instead of installing heavy model dependencies |
| `TC-09-003` | `tests/test_analytics_agent.py::test_analytics_agent_falls_back_to_moving_average_when_fit_fails` |
| `TC-09-004` | `tests/test_analytics_agent.py::test_analytics_agent_narrative_uses_fact_judgment_uncertainty_sections` |
| `TC-09-005` | `tests/test_frontend_backend_flow.py::test_frontend_app_shell_renders_analytics_props_from_real_backend_forecast` verifies forecast request -> backend -> analytics -> API -> frontend props |
| `TC-09-006` | `tests/test_analytics_agent.py::test_analytics_agent_empty_series_returns_quality_error_not_model_crash` |

## Integration Coverage

| Layer | Verification |
|---|---|
| Agent unit behavior | `tests/test_analytics_agent.py` |
| Orchestrator forecast routing | `tests/test_simple_orchestrator.py::test_orchestrator_uses_execution_plan_for_forecast_question` |
| API response contract | `tests/test_api_models.py::test_query_answer_converts_to_chat_query_response_payload`; `tests/test_api_models.py::test_success_envelope_contains_trace_id_and_required_answer_fields` |
| Frontend parsing | `tests/test_frontend_view_models.py::test_build_query_result_view_model_renders_distinct_blocks` |
| Frontend component props | `tests/test_frontend_component_props.py::test_build_chat_page_props_includes_analytics_insight_props`; `tests/test_frontend_component_props.py::test_build_chat_page_props_localizes_analytics_labels` |
| Frontend/backend end to end | `tests/test_frontend_backend_flow.py::test_frontend_app_shell_renders_analytics_props_from_real_backend_forecast` |

## Design Notes

The current analytics slice is deterministic and dependency-light.

In plain terms:

1. `analytics_agent.py` is the analysis teacher: it checks whether the time series is usable, detects unusual points, forecasts future values, and explains the result.
2. `simple_orchestrator.py` is the classroom coordinator: when the question looks like a forecast, it sends the revenue time series to the analytics agent and attaches the result to the final answer.
3. `api/models.py` is the public handout: it exposes `analytics_result` so API callers can see the forecast, anomaly result, narrative, warnings, and model metadata.
4. `view_models.py` turns the API's analytics JSON into a small frontend card model.
5. `component_props.py` turns that card model into display-ready labels and narrative lines.

The MVP does not install real ARIMA or Prophet packages. Instead, `ARIMA` and `PROPHET` requests use a deterministic trend-style calculation, and failed fits fall back to moving average. This keeps the implementation reproducible and fast while preserving the spec-level output contract.

## Known Gaps

| Gap | Reason |
|---|---|
| Real ARIMA/Prophet fitting | Deferred to avoid heavy dependencies in the in-memory MVP |
| Formal 90-day P95 latency benchmark | Needs a defined benchmark fixture, runner, and statistical window |
| Sustained model failure alerting | Requires observability/alert state from spec 10 |
| Holiday calendar / drift monitoring | Listed as open questions in the spec |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Focused static check:

```bash
.venv/bin/pyright tests/test_frontend_backend_flow.py
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Focused test suite:

```bash
.venv/bin/python -m pytest tests/test_frontend_backend_flow.py
```

Result:

```text
2 passed, 1 warning
```

Full static check:

```bash
.venv/bin/pyright
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Full test suite:

```bash
.venv/bin/python -m pytest
```

Result:

```text
252 passed, 1 warning
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient
```

This warning comes from the third-party FastAPI/TestClient stack and does not indicate a failing project test.
