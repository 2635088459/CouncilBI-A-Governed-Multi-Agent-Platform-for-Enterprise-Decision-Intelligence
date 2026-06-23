# Verification: 02 Agent Orchestration

This document records the current machine-verifiable status for the first implementation slice based on `spec/version1/02-agent-orchestration.spec.md`.

## Scope

Verified workflows:

```text
question
  -> QuestionClassifier
  -> TaskType
  -> ExecutionPlanBuilder
  -> ordered agent plan

agent step
  -> AgentStepTracer
  -> start event
  -> terminal event
  -> duration/status

agent confidence scores
  -> ConfidenceAggregator
  -> weighted final confidence
  -> low-confidence warning

execution plan
  -> PlanExecutor
  -> run configured agent runners
  -> skip dependent agents on SQL failure
  -> degraded result warnings

application flow
  -> SimpleOrchestrator
  -> QuestionClassifier
  -> ExecutionPlanBuilder
  -> PlanExecutor
  -> persisted QueryHistoryRecord

SQL agent adapter
  -> SqlAgentRunner
  -> SimpleSqlGuardrail
  -> safe_sql or structured AgentStepError

Visualization agent adapter
  -> VisualizationAgentRunner
  -> chart payload
  -> chart field validation

Analytics agent adapter
  -> AnalyticsAgentRunner
  -> model payload
  -> metric and horizon validation

RAG agent adapter
  -> RagAgentRunner
  -> evidence payload
  -> citation validation

Verifier agent adapter
  -> VerifierAgentRunner
  -> verification payload
  -> confidence and reason validation

orchestration output aggregation
  -> chart payload to QueryAnswer.chart_spec
  -> RAG payload to QueryAnswer.evidence_list
  -> execution confidence to QueryAnswer.confidence
```

This slice verifies classification, plan construction, in-memory step tracing, confidence aggregation, a mock-agent execution harness, integration with `SimpleOrchestrator`, and first-pass SQL, visualization, analytics, RAG, and verifier agent adapters. It does not execute real database queries, statistical models, vector retrieval, or LLM verification yet.

Covered requirements:

| Requirement | Verification |
|---|---|
| `FR-02-001` | `tests/test_agent_orchestration_routing.py` |
| `FR-02-002` | `tests/test_agent_orchestration_routing.py`, `tests/test_simple_orchestrator.py` |
| `FR-02-003` | `tests/test_agent_orchestration_routing.py`, `tests/test_simple_orchestrator.py` |
| `FR-02-005` | `tests/test_agent_orchestration_routing.py` for why-question verifier ordering |
| `FR-02-006` | `tests/test_plan_executor.py` |
| `FR-02-007` | `tests/test_plan_executor.py` |
| `FR-02-008` | `tests/test_plan_executor.py` |
| `NFR-02-004` | `tests/test_agent_step_tracing.py` |
| `AC-02-001` | KPI query plan routes to SQL Agent + Visualization Agent |
| `AC-02-002` | Forecast question plan routes to SQL Agent + Analytics Agent |
| `AC-02-003` | Why-question plan routes to SQL Agent + RAG Agent + Verifier Agent |
| `AC-02-004` | SQL timeout returns degraded execution result and skipped fanout |
| `AC-02-005` | Agent step trace events include status and duration |
| `AC-02-006` | Low confidence creates a high-risk warning |
| `TC-02-001` | Classifier maps question types to task categories |
| `TC-02-002` | Confidence aggregation computes expected weighted score |
| `TC-02-005` | SQL Agent timeout triggers degraded response with warning |
| `TC-02-006` | Fanout agent failure still returns a degraded result with successful outputs |
| SQL adapter | `tests/test_sql_agent.py` verifies allowed and denied SQL behavior |
| Visualization adapter | `tests/test_visualization_agent.py` verifies chart payload generation |
| Analytics adapter | `tests/test_analytics_agent.py` verifies analytics payload generation |
| RAG adapter | `tests/test_rag_agent.py` verifies evidence payload generation |
| Verifier adapter | `tests/test_verifier_agent.py` verifies verification payload generation |
| Output aggregation | `tests/test_simple_orchestrator.py` verifies chart and evidence attachment |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Layer 1 static check:

```bash
.venv/bin/python -m pyright
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
70 passed, 1 warning
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient
```

This warning comes from the third-party FastAPI/TestClient stack and does not indicate a failing project test.

## Next Slice

Recommended next implementation slice:

```text
decide next spec boundary
  -> deepen 02 orchestration with real adapters
  -> or move to 03 semantic layer / NL2SQL
```

The current 02 slice is broad enough for the architecture demo. Further depth should be chosen based on project priority.
