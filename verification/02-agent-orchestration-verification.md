# Verification: 02 Agent Orchestration v2

This document records the current machine-verifiable status for
`spec/version2/02-agent-orchestration.spec.md`.

## Verified Runtime Slice

```text
QueryRequest
  -> SimpleOrchestrator
  -> QuestionClassifier
  -> ExecutionPlanBuilder
  -> PlanExecutor
  -> AgentStepTracer
  -> OrchestrationStateStore
  -> Agent runners
  -> VerifierAgentRunner
  -> AnswerAssemblyVerifier
  -> QueryAnswer
  -> QueryHistoryRecord
```

Verified orchestration components now include:

- `OrchestrationRequest`, `AgentStepInput`, `AgentStepOutput`, and typed step/status enums
- v2 task classification into `sql_query`, `chart`, `analytics`, `rag_explanation`, and `verification`
- ordered execution plans with SQL before Visualization, Analytics, and RAG
- Verifier execution before final answer assembly
- step-level idempotency keys using `trace_id:step_name:attempt`
- retry attempt state tracking up to the configured cap
- timeout output with `AGENT_TIMEOUT` in trace and state
- degraded non-critical Agent output, including `RAG_UNAVAILABLE`
- request-level in-flight state keyed by `trace_id`
- Redis-shaped in-memory orchestration state store
- PostgreSQL-shaped trace repository boundary
- worker handoff queue that creates task ids for analytics and indexing work
- final answer assembly verification before history persistence

## Coverage Matrix

| ID | Status | Verification |
|---|---|---|
| `VR-02-001` | Covered | `AgentStepInput.idempotency_key`, `tests/test_agent_orchestration_contracts.py`, `tests/test_plan_executor.py` |
| `VR-02-002` | Covered | SQL denial skips Visualization and Verifier in `tests/test_plan_executor.py`; routing dependencies in `tests/test_agent_orchestration_routing.py` |
| `VR-02-003` | Covered | RAG failure returns degraded output with `RAG_UNAVAILABLE` in `tests/test_plan_executor.py`; final degraded request state in `tests/test_simple_orchestrator.py` |
| `VR-02-004` | Covered | Timeout trace has `TIMED_OUT` and `AGENT_TIMEOUT`; state stores `AGENT_TIMEOUT`. See `tests/test_agent_step_tracing.py`, `tests/test_plan_executor.py`, `tests/test_orchestration_state.py` |
| `VR-02-005` | Covered | Shared state store avoids duplicate step execution after a new `PlanExecutor` simulates orchestrator restart in `tests/test_plan_executor.py` |
| `FR-02-001` | Covered | `QuestionClassifier` and `classify_many` in `tests/test_agent_orchestration_routing.py` |
| `FR-02-002` | Covered by repository boundary | `AgentTraceRepository`, `InMemoryAgentTraceLog`, and start/terminal event tests in `tests/test_agent_step_tracing.py`; durable PostgreSQL adapter remains a future replacement |
| `FR-02-003` | Covered by Redis-shaped state boundary | `OrchestrationRequestState` and `InMemoryOrchestrationStateStore` in `tests/test_orchestration_state.py`, request-state integration in `tests/test_simple_orchestrator.py` |
| `FR-02-004` | Covered | SQL dependency is required before Visualization, Analytics, and RAG in `tests/test_agent_orchestration_routing.py` and `tests/test_plan_executor.py` |
| `FR-02-005` | Covered | Verifier appears in SQL-only trace before orchestrator completion; verifier findings flow into final answer warnings. See `tests/test_simple_orchestrator.py`, `tests/test_verifier_agent.py`, `tests/test_answer_verification.py` |
| `FR-02-006` | Covered | `WorkerHandoffQueue` creates `task_...` ids for analytics and indexing in `tests/test_worker_handoff.py` |
| `NFR-02-001` | Covered as local smoke | 500-question classifier P95 smoke in `tests/test_agent_orchestration_routing.py` |
| `NFR-02-002` | Covered for in-memory repository | start and terminal trace events are asserted in `tests/test_agent_step_tracing.py`, `tests/test_plan_executor.py`, and `tests/test_simple_orchestrator.py` |
| `NFR-02-003` | Covered | repeated submissions and restart recovery keep runner call count at zero/one as expected in `tests/test_plan_executor.py` |
| `NFR-02-004` | Covered for added orchestration modules | Pyright commands listed below |
| `AC-02-001` | Covered | SQL-only request creates `orchestrator`, `sql`, and `verifier` successful trace steps in `tests/test_simple_orchestrator.py` |
| `AC-02-002` | Covered | chart request with denied SQL never starts Visualization in `tests/test_plan_executor.py` |
| `AC-02-003` | Covered | failed RAG step returns degraded output and `RAG_UNAVAILABLE` warning in `tests/test_plan_executor.py` |
| `AC-02-004` | Covered | timed-out step stores `AGENT_TIMEOUT` in trace summary and state in `tests/test_agent_step_tracing.py`, `tests/test_plan_executor.py`, `tests/test_orchestration_state.py` |
| `AC-02-005` | Covered | replay with same idempotency key returns previous output without executing Agent again in `tests/test_plan_executor.py` |

## Test Map

| Test file | What it proves |
|---|---|
| `tests/test_agent_orchestration_contracts.py` | v2 request/step contracts, attempts, deadlines, timeout output |
| `tests/test_agent_orchestration_routing.py` | task classification, execution plans, SQL-before-fanout, classifier P95 smoke |
| `tests/test_plan_executor.py` | step execution, skip rules, retries, timeout, degraded RAG failure, idempotency, restart recovery |
| `tests/test_agent_step_tracing.py` | trace repository contract, start/success/failure/timeout/skipped events |
| `tests/test_orchestration_state.py` | request-level state, step-level state, successful-step filtering |
| `tests/test_worker_handoff.py` | async task id creation for analytics and indexing handoff |
| `tests/test_verifier_agent.py` | verifier payload, missing SQL, missing fields, upstream warnings |
| `tests/test_answer_verification.py` | final answer assembly checks and `VERIFICATION_FAILED` warnings |
| `tests/test_simple_orchestrator.py` | end-to-end local orchestrator flow, history persistence, request state, verifier and final answer warning integration |
| `tests/test_orchestration_exports.py` | public package exports for v2 orchestration contracts |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Focused v2 orchestration tests:

```bash
.venv/bin/python -m pytest \
  tests/test_agent_orchestration_contracts.py \
  tests/test_agent_orchestration_routing.py \
  tests/test_plan_executor.py \
  tests/test_agent_step_tracing.py \
  tests/test_orchestration_state.py \
  tests/test_worker_handoff.py \
  tests/test_verifier_agent.py \
  tests/test_answer_verification.py \
  tests/test_simple_orchestrator.py \
  tests/test_orchestration_exports.py
```

Recent focused result:

```text
68 passed
```

Full local suite:

```bash
.venv/bin/python -m pytest -q
```

Recent full result:

```text
378 passed, 1 skipped, 1 warning
```

Static type checks used while building this slice:

```bash
.venv/bin/pyright \
  src/chatbi/orchestration/contracts.py \
  src/chatbi/orchestration/routing.py \
  src/chatbi/orchestration/executor.py \
  src/chatbi/orchestration/tracing.py \
  src/chatbi/orchestration/state.py \
  src/chatbi/orchestration/worker.py \
  src/chatbi/orchestration/answer_verification.py \
  src/chatbi/orchestration/simple_orchestrator.py \
  src/chatbi/agents/verifier_agent.py
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

The following items are intentionally represented by local/in-memory boundaries:

- `FR-02-002`: trace persistence has a PostgreSQL-shaped repository boundary, but no concrete PostgreSQL `agent_traces` adapter yet.
- `FR-02-003`: request and step state have a Redis-shaped store, but no concrete Redis adapter yet.
- `FR-02-006`: worker handoff creates task ids through an in-memory queue, but is not connected to a real Redis queue or worker process yet.
- Parallel fanout is represented by dependency-aware ordered execution; true concurrent execution is not implemented in this local slice.
- Deadline enforcement is represented through runner-raised `TimeoutError`; wall-clock cancellation is not implemented yet.

## Next Recommended Step

Move to one of these implementation slices:

```text
Option A:
  implement RedisOrchestrationStateStore
  -> keep OrchestrationStateStore interface unchanged
  -> verify request and step state through a Redis integration test

Option B:
  implement PostgresAgentTraceRepository
  -> keep AgentTraceRepository interface unchanged
  -> verify start/terminal trace rows by trace_id

Option C:
  connect WorkerHandoffQueue to a real task-status API
  -> expose task_id lookup through backend API
```
