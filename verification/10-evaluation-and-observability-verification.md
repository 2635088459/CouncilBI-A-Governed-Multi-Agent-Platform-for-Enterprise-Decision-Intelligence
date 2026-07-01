# Verification: 10 Evaluation and Observability

This document records the current machine-verifiable status for `spec/version2/10-evaluation-and-observability.spec.md`.

## Scope

Verified v2 workflow:

```text
/api/v1/chat/query
  -> backend TraceEvent
  -> standard observability spans
  -> orchestrator/agent trace records
  -> SQL guardrail allow/deny audit
  -> masked JSON observability logs
  -> final query history record
  -> trace detail by trace_id

/healthz, /readyz, /metrics
  -> runtime probes
  -> request/error/latency metrics text
  -> local latency smoke coverage

eval cases
  -> EvalRunner
  -> eval_run rows
  -> eval_score rows
  -> eval_failure rows
  -> EvalRunReport
  -> /api/v1/evals/run and /api/v1/evals/{eval_run_id}

release process
  -> pyright gate
  -> pytest gate
  -> SQL safety evaluation gate
  -> human acceptance review after machine gates pass
```

Covered implementation files:

| Area | File |
|---|---|
| Spec-facing trace events | `src/chatbi/trace_events.py` |
| Standard spans, SLO status, alert rules | `src/chatbi/observability.py` |
| Runtime metrics renderer | `src/chatbi/runtime_metrics.py` |
| Masked structured JSON logs | `src/chatbi/observability_logs.py` |
| Eval case loading | `src/chatbi/evaluation_cases.py` |
| Eval run/score/failure persistence | `src/chatbi/evaluation_repository.py` |
| Eval report read model | `src/chatbi/evaluation_report.py` |
| Trace and eval benchmarks | `src/chatbi/trace_benchmark.py`, `src/chatbi/evaluation_benchmark.py` |
| Release gate process | `src/chatbi/release_gate.py` |
| CI order model | `src/chatbi/release_gate_ci.py` |
| GitHub Actions release gate | `.github/workflows/spec-10-release-gate.yml` |
| Human acceptance review | `src/chatbi/human_acceptance.py` |
| Application integration | `src/chatbi/application/app.py` |
| API payloads and routes | `src/chatbi/api/models.py`, `src/chatbi/api/http.py` |
| Spec-10 public facade | `src/chatbi/evaluation_observability_v2.py` |

## Requirement Coverage

| Requirement | Verification |
|---|---|
| `FR-10-001` | `tests/test_runtime_probes.py` verifies `/healthz`, `/readyz`, and `/metrics`; `tests/test_runtime_metrics.py` verifies required metric text. |
| `FR-10-002` | `tests/test_app.py::test_handle_chat_query_writes_spec_trace_events` verifies backend `TraceEvent` rows; `tests/test_simple_orchestrator.py::test_orchestrator_writes_spec_trace_events_for_success` verifies orchestrator `TraceEvent` rows; HTTP trace detail tests verify both services appear by `trace_id`. |
| `FR-10-003` | `tests/test_simple_orchestrator.py::test_orchestrator_writes_guardrail_audit_for_allowed_sql` and `tests/test_simple_orchestrator.py::test_orchestrator_writes_guardrail_audit_for_denied_sql` verify allow and deny SQL audit records. |
| `FR-10-004` | `tests/test_evaluation_cases.py`, `tests/test_evaluation_repository.py`, and `tests/test_evaluation_report.py` verify eval case loading plus saved runs, scores, failures, and reports. |
| `FR-10-005` | `tests/test_release_gate.py::test_release_gate_stops_after_pyright_failure` verifies pyright failure skips later gates. |
| `FR-10-006` | `tests/test_release_gate.py::test_release_gate_stops_after_pytest_failure` verifies pytest failure skips evaluation and human acceptance. |
| `FR-10-007` | `tests/test_release_gate.py::test_release_gate_blocks_sql_safety_below_one_hundred_percent` verifies SQL safety below 100% blocks release. |

## Validation Rules

| Rule | Verification |
|---|---|
| `VR-10-001` | `tests/test_app.py::test_handle_chat_query_writes_spec_trace_events` verifies each accepted chat query emits trace events with `trace_id`. |
| `VR-10-002` | `tests/test_observability_logs.py::test_observability_log_renders_as_json_with_trace_id` verifies logs render as JSON and include `trace_id`; app tests verify masking. |
| `VR-10-003` | `tests/test_runtime_metrics.py` and `tests/test_runtime_probes.py` verify request count, error count, and latency summary names. |
| `VR-10-004` | `tests/test_evaluation_repository.py::test_eval_runner_release_gate_fails_when_dangerous_sql_is_not_blocked` and release-gate tests verify dangerous SQL safety failure blocks release. |
| `VR-10-005` | `tests/test_release_gate.py::test_human_acceptance_cannot_override_machine_gate_failure` and `tests/test_human_acceptance.py::test_human_acceptance_cannot_override_machine_gate_failure` verify human review cannot override machine failures. |

## Acceptance Criteria

| Acceptance Criterion | Verification |
|---|---|
| `AC-10-001` | `tests/test_http_app.py::test_observability_trace_endpoint_returns_standard_spans` verifies one `trace_id` returns spans, spec trace events, final query detail, API audit, guardrail audit, and logs. |
| `AC-10-002` | `tests/test_runtime_probes.py` and `tests/test_runtime_metrics.py` verify `/metrics` contains request, error, and latency metric names. |
| `AC-10-003` | `tests/test_evaluation_repository.py::test_eval_runner_persists_one_run_and_one_score_per_case` verifies one run and one score per case; failure tests verify failure rows. |
| `AC-10-004` | `tests/test_release_gate.py::test_release_gate_blocks_sql_safety_below_one_hundred_percent` verifies SQL safety below 1.0 fails the release gate. |
| `AC-10-005` | `tests/test_release_gate_ci.py::test_default_release_gate_ci_plan_runs_pyright_before_pytest` and release-gate stop tests verify CI order and stop behavior. |

## Test Plan Mapping

| Test Case | Current Verification |
|---|---|
| `TC-10-001` | Focused pyright over trace, eval, metrics, release gate, human acceptance, and facade modules reports 0 errors. |
| `TC-10-002` | `tests/test_app.py`, `tests/test_http_app.py::test_observability_trace_endpoint_returns_standard_spans`, and trace store tests inspect trace-linked records. |
| `TC-10-003` | `tests/test_runtime_metrics.py`, `tests/test_runtime_probes.py`, and `tests/test_runtime_latency_smoke.py`. |
| `TC-10-004` | `tests/test_evaluation_repository.py`, `tests/test_evaluation_cases.py`, `tests/test_evaluation_report.py`, and eval HTTP report tests. |
| `TC-10-005` | `tests/test_release_gate.py` and dangerous SQL eval repository tests. |
| `TC-10-006` | `tests/test_trace_benchmark.py::test_trace_lookup_benchmark_runs_over_ten_thousand_events_under_local_budget`. |
| `TC-10-007` | `tests/test_release_gate_ci.py` and `tests/test_spec10_release_gate_workflow.py` verify pyright runs before pytest and human acceptance runs after machine gates. |
| `TC-10-008` | `tests/test_human_acceptance.py` verifies human review on a successful example and rejects machine-gate override. |

## Integration Coverage

| Layer | Verification |
|---|---|
| Trace contracts and store | `tests/test_trace_events.py`, `tests/test_observability_trace_store.py` |
| Runtime probes and metrics | `tests/test_runtime_probes.py`, `tests/test_runtime_metrics.py`, `tests/test_runtime_latency_smoke.py` |
| Structured logs | `tests/test_observability_logs.py`, `tests/test_app.py::test_handle_chat_query_writes_sanitized_observability_logs` |
| Orchestrator trace and SQL audit | `tests/test_simple_orchestrator.py`, `tests/test_app.py::test_observability_trace_detail_includes_denied_guardrail_audit` |
| Eval persistence and report | `tests/test_evaluation_cases.py`, `tests/test_evaluation_repository.py`, `tests/test_evaluation_report.py` |
| Eval API | `tests/test_http_app.py::test_eval_run_endpoint_returns_quality_report`, `tests/test_http_app.py::test_eval_report_endpoint_returns_saved_eval_run_report` |
| Quality dashboard | `tests/test_api_models.py::test_quality_dashboard_payload_includes_slo_and_release_gate_summary`, `tests/test_http_app.py::test_quality_dashboard_endpoint_includes_latest_release_gate_result` |
| Release process | `tests/test_release_gate.py`, `tests/test_release_gate_ci.py`, `tests/test_human_acceptance.py` |
| CI workflow | `tests/test_spec10_release_gate_workflow.py` |
| Public facade | `tests/test_evaluation_observability_v2_exports.py` |

## Design Notes

In plain terms:

1. `trace_events.py` is the small spec-facing trace table. It stores the minimum trace-event shape required by the spec: service, span name, status, timestamps, and latency.
2. `observability.py` is the older span and SLO engine. It helps replay request spans and evaluate error-rate or latency health.
3. `observability_logs.py` is the safe log printer. It masks sensitive values and can render compact JSON lines with `trace_id`.
4. `evaluation_repository.py` is the eval database contract. The current implementation is in memory, but the methods are shaped like future `eval_run`, `eval_score`, and `eval_failure` tables.
5. `evaluation_report.py` is the grade sheet. It turns saved rows into one dashboard-friendly report.
6. `release_gate.py` is the process guard. It enforces pyright before pytest, pytest before evaluation, and machine gates before human review.
7. `release_gate_ci.py` is the CI class schedule. It does not execute shell commands; it makes the intended order testable.
8. `human_acceptance.py` is the human review form. It only runs after machine gates pass and cannot override failed machine checks.
9. `application/app.py` ties the pieces together for local API use: chat query tracing, runtime samples, logs, eval execution, eval report lookup, and dashboard summaries.

## Known Gaps

| Gap | Reason |
|---|---|
| Stores are mostly in-memory | This is the local teaching/MVP implementation; production should back trace, log, and eval repositories with durable storage. |
| `src/chatbi/api/http.py` full-file pyright still depends on FastAPI/Pydantic environment resolution | Focused core modules pass pyright; HTTP behavior is covered by pytest. |
| Human acceptance still needs reviewer judgment in PRs | The workflow prints the checklist after machine gates pass; business correctness cannot be fully automated. |
| External APM/log shipping is not implemented | Out of scope for spec v2, which excludes building a custom APM product. |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv313
Python: 3.13.13
Date: 2026-07-01
```

Focused spec-10 test suite:

```bash
.venv313/bin/python -m pytest \
  tests/test_trace_events.py \
  tests/test_runtime_metrics.py \
  tests/test_runtime_probes.py \
  tests/test_observability_logs.py \
  tests/test_evaluation_repository.py \
  tests/test_evaluation_cases.py \
  tests/test_evaluation_report.py \
  tests/test_simple_orchestrator.py \
  tests/test_release_gate.py \
  tests/test_release_gate_ci.py \
  tests/test_spec10_release_gate_workflow.py \
  tests/test_human_acceptance.py \
  tests/test_trace_benchmark.py \
  tests/test_evaluation_benchmark.py \
  tests/test_app.py
```

Result:

```text
79 passed, 1 warning
```

Focused static check:

```bash
.venv313/bin/python -m pyright \
  src/chatbi/trace_events.py \
  src/chatbi/runtime_metrics.py \
  src/chatbi/observability_logs.py \
  src/chatbi/evaluation_repository.py \
  src/chatbi/evaluation_cases.py \
  src/chatbi/evaluation_report.py \
  src/chatbi/release_gate.py \
  src/chatbi/release_gate_ci.py \
  src/chatbi/human_acceptance.py \
  src/chatbi/trace_benchmark.py \
  src/chatbi/evaluation_benchmark.py \
  src/chatbi/evaluation_observability_v2.py
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient
```

This warning comes from the third-party FastAPI/TestClient stack and does not indicate a failing project test.
