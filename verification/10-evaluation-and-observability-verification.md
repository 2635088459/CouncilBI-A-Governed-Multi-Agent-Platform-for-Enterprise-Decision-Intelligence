# Verification: 10 Evaluation and Observability

This document records the current machine-verifiable status for `spec/version1/10-evaluation-and-observability.spec.md`.

## Scope

Verified workflow:

```text
offline benchmark observations
  -> EvaluationScorer
  -> metric_breakdown and failed_cases
  -> release_gate_passed
  -> /api/v1/evals/run

/api/v1/chat/query
  -> standard observability spans
  -> in-memory trace replay
  -> runtime request samples
  -> SLO status and alert evaluation
  -> /api/v1/quality/dashboard

chat query logs
  -> LogSanitizer
  -> ObservabilityLogger
  -> masked observability log store
```

Covered implementation files:

| Area | File |
|---|---|
| Offline evaluation and release gate | `src/chatbi/evaluation.py` |
| Alert rules, SLO status, trace spans, trace store | `src/chatbi/observability.py` |
| Masked observability logs | `src/chatbi/observability_logs.py` |
| API payload contracts | `src/chatbi/api/models.py` |
| Application integration | `src/chatbi/application/app.py` |
| HTTP routes | `src/chatbi/api/http.py` |

## Covered Requirements

| Requirement | Verification |
|---|---|
| `FR-10-001` | `tests/test_http_app.py::test_eval_run_endpoint_returns_quality_report` verifies `/api/v1/evals/run` runs a benchmark-style suite and returns a report |
| `FR-10-002` | `tests/test_evaluation.py::test_evaluation_report_passes_clean_benchmark_suite` verifies SQL accuracy, SQL safety, agent routing, and RAG faithfulness scoring |
| `FR-10-003` | `tests/test_evaluation.py::test_release_gate_blocks_missed_dangerous_sql`, `tests/test_evaluation.py::test_release_gate_blocks_unsupported_claim_rate_over_slo`, and `tests/test_evaluation.py::test_release_gate_blocks_chat_query_p95_latency_over_slo` verify release gate failures |
| `FR-10-004` | `tests/test_app.py::test_handle_chat_query_writes_standard_observability_trace` and `tests/test_observability_trace_store.py::test_standard_trace_span_names_match_spec_order` verify standard span emission |
| `FR-10-005` | `tests/test_observability.py::test_e2e_error_rate_over_two_percent_for_ten_minutes_fires_alert` verifies E2E error-rate alerting |
| `FR-10-006` | `tests/test_observability.py::test_chat_query_p95_latency_over_eight_seconds_for_fifteen_minutes_fires_alert` verifies P95 latency alerting |
| `FR-10-007` | `tests/test_observability_trace_store.py::test_observability_store_replays_spans_by_trace_id` and `tests/test_http_app.py::test_observability_trace_endpoint_returns_standard_spans` verify replay by `trace_id` |
| `FR-10-008` | `tests/test_http_app.py::test_eval_run_endpoint_returns_quality_report` verifies `overall_score`, `metric_breakdown`, and failed-case counts are returned |
| `NFR-10-001` | Trace writes are synchronous in-memory append operations; full latency-overhead benchmark remains future work |
| `NFR-10-002` | `tests/test_observability.py::test_alert_evaluator_requires_minimum_sample_count_to_reduce_noise` verifies minimum sample count noise control |
| `NFR-10-003` | `tests/test_observability_logs.py` and `tests/test_app.py::test_handle_chat_query_writes_sanitized_observability_logs` verify log PII masking |

## Acceptance Criteria

| Acceptance Criterion | Verification |
|---|---|
| `AC-10-001` | `tests/test_evaluation.py::test_release_gate_blocks_missed_dangerous_sql` verifies SQL safety failure blocks the release gate |
| `AC-10-002` | `tests/test_observability.py::test_e2e_error_rate_over_two_percent_for_ten_minutes_fires_alert` verifies error-rate alert firing |
| `AC-10-003` | `tests/test_http_app.py::test_observability_trace_endpoint_returns_standard_spans` verifies trace replay returns request-path spans including SQL details |
| `AC-10-004` | `tests/test_http_app.py::test_quality_dashboard_endpoint_returns_active_slo_statuses` verifies active SLOs are visible in `/api/v1/quality/dashboard` |
| `AC-10-005` | `tests/test_observability_logs.py::test_observability_logger_stores_only_sanitized_records` and `tests/test_app.py::test_handle_chat_query_writes_sanitized_observability_logs` verify raw PII is absent from logs |

## Test Plan Mapping

| Test Case | Current Verification |
|---|---|
| `TC-10-001` | `tests/test_evaluation.py` verifies scoring functions on known inputs |
| `TC-10-002` | `tests/test_http_app.py::test_eval_run_endpoint_returns_quality_report` verifies full evaluation run output |
| `TC-10-003` | `tests/test_observability_trace_store.py::test_observability_store_replays_spans_by_trace_id`; `tests/test_http_app.py::test_observability_trace_endpoint_returns_standard_spans` |
| `TC-10-004` | `tests/test_evaluation.py::test_release_gate_blocks_missed_dangerous_sql` |
| `TC-10-005` | `tests/test_observability.py::test_e2e_error_rate_over_two_percent_for_ten_minutes_fires_alert` |
| `TC-10-006` | `tests/test_observability_logs.py`; `tests/test_app.py::test_handle_chat_query_writes_sanitized_observability_logs` |

## Integration Coverage

| Layer | Verification |
|---|---|
| Evaluation unit behavior | `tests/test_evaluation.py` |
| Alert and SLO unit behavior | `tests/test_observability.py` |
| Trace store and replay | `tests/test_observability_trace_store.py` |
| Masked logs | `tests/test_observability_logs.py` |
| Application integration | `tests/test_app.py::test_handle_chat_query_writes_standard_observability_trace`; `tests/test_app.py::test_handle_chat_query_writes_sanitized_observability_logs` |
| HTTP evaluation endpoint | `tests/test_http_app.py::test_eval_run_endpoint_returns_quality_report` |
| HTTP trace replay endpoint | `tests/test_http_app.py::test_observability_trace_endpoint_returns_standard_spans` |
| HTTP quality dashboard endpoint | `tests/test_http_app.py::test_quality_dashboard_endpoint_returns_active_slo_statuses`; `tests/test_http_app.py::test_quality_dashboard_endpoint_includes_latest_release_gate_result`; `tests/test_http_app.py::test_quality_dashboard_endpoint_uses_recorded_chat_query_samples` |

## Design Notes

The current implementation is an in-memory, deterministic MVP.

In plain terms:

1. `evaluation.py` is the exam grader. It compares benchmark expectations with observed system outputs and decides whether the release gate passes.
2. `observability.py` is the monitoring engine. It stores standard trace spans, replays spans by `trace_id`, calculates SLO status, and fires alert events from runtime samples.
3. `observability_logs.py` is the safe logging door. It accepts human-readable logs but masks emails, phone numbers, user ids, session ids, customer ids, and customer names before saving.
4. `application/app.py` is the coordinator. It records spans, runtime samples, masked logs, latest evaluation results, and dashboard data during normal API use.
5. `api/http.py` exposes the operational surfaces: `/api/v1/evals/run`, `/api/v1/observability/traces/{trace_id}`, and `/api/v1/quality/dashboard`.

This keeps the architecture small enough to understand while preserving the key production ideas: quality gates, alert rules, trace replay, dashboard state, and safe logs.

## Known Gaps

| Gap | Reason |
|---|---|
| Observability store is in-memory | Production persistence would use a database, log store, or APM backend |
| Alert evaluator has no background scheduler | Current API evaluates alerts from recorded samples on demand |
| Formal `NFR-10-001` trace-overhead benchmark is not implemented | The MVP uses synchronous in-memory appends, but no statistical latency benchmark has been added |
| Monthly E2E success-rate aggregation is not implemented | Current SLO dashboard covers active rule health from runtime samples, not calendar-month rollups |
| Automated incident workflow is not implemented | Alert events are returned by API but not sent to PagerDuty, Slack, email, or ticketing |
| Frontend quality dashboard page is not implemented | Backend API data contract is ready for a future frontend view |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Focused static check:

```bash
.venv/bin/pyright src/chatbi/evaluation.py src/chatbi/observability.py src/chatbi/observability_logs.py src/chatbi/application/app.py src/chatbi/api/http.py src/chatbi/api/models.py
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Focused test suite:

```bash
.venv/bin/pytest tests/test_evaluation.py tests/test_observability.py tests/test_observability_trace_store.py tests/test_observability_logs.py tests/test_app.py tests/test_http_app.py
```

Result:

```text
51 passed, 1 warning
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
.venv/bin/pytest
```

Result:

```text
282 passed, 1 warning
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient
```

This warning comes from the third-party FastAPI/TestClient stack and does not indicate a failing project test.
