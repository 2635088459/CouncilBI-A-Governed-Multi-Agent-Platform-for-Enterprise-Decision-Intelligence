# Spec: Agent Orchestration

## 1. Purpose
Define how the Orchestrator classifies tasks, routes to specialized agents, and assembles partial results into one answer.

## 2. Scope
In scope:
- Task classification and routing
- Execution plan construction
- Parallel/serial dispatch
- Retry, timeout, and fallback
- Confidence aggregation

Out of scope:
- Provider-specific LLM infra switching
- Distributed queue disaster recovery

Assumptions:
- Agents are co-located in the same service in v1.
- SQL Agent always runs before fanout agents.

Constraints:
- Orchestrator MUST NOT write to the database directly.
- Every agent step MUST be logged with trace_id.

## 3. Agents
- Orchestrator, SQL Agent, Visualization Agent, Analytics Agent, RAG Agent, Verifier Agent

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-02-001 | The Orchestrator MUST classify every incoming question into a known task type. |
| FR-02-002 | The Orchestrator MUST build an execution plan before dispatching any agent. |
| FR-02-003 | SQL Agent MUST complete before Visualization, Analytics, or RAG agents start. |
| FR-02-004 | Visualization, Analytics, and RAG agents SHOULD run in parallel after SQL completes. |
| FR-02-005 | Verifier MUST run after all branch agents return. |
| FR-02-006 | Any timed-out agent MUST be skipped and its absence reflected in warnings. |
| FR-02-007 | The final answer MUST aggregate outputs from all successful agents. |
| FR-02-008 | A degraded response MUST explicitly state which agents could not complete. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-02-001 | Routing accuracy MUST be >= 95% on the benchmark question set. |
| NFR-02-002 | Per-agent execution timeout MUST be <= 8s. |
| NFR-02-003 | Total orchestration timeout MUST be <= 25s. |
| NFR-02-004 | Each agent step MUST emit start, finish, duration, and status events. |

## 6. State Machine
- Received → Classified → SQLRunning → FanoutRunning → Verifying → Completed
- Any step → Degraded → Completed on failure

## 7. Collaboration Rules
- Deny overrides: SQL blocked → skip fanout → return safe error.
- Confidence: weighted average of SQL (0.35), Verifier (0.35), RAG (0.15), Analytics (0.15).
- confidence < 0.6 → high-risk warning appended.

## 8. Contracts

Input:
```
trace_id, session_id, user_role, question, locale
```

Agent output standard fields:
```
status (success|partial|failed), payload, confidence, warnings, metrics
```

Final output:
```
answer_text, sql, table, chart, evidence, warnings, confidence, trace_id
```

## 9. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-02-001 | A KPI query routes to SQL Agent + Visualization Agent. |
| AC-02-002 | A forecast question routes to SQL Agent + Analytics Agent. |
| AC-02-003 | A why-question routes to SQL Agent + RAG Agent + Verifier Agent. |
| AC-02-004 | If SQL Agent times out, the response returns a degraded answer with a warning. |
| AC-02-005 | Every answer has a per-step trace in the audit log. |
| AC-02-006 | confidence < 0.6 results in a high-risk warning in the response. |

## 10. Test Plan

| ID | Type | Description |
|---|---|---|
| TC-02-001 | Unit | Classifier maps question types to correct task categories. |
| TC-02-002 | Unit | Confidence aggregation computes expected weighted score. |
| TC-02-003 | Integration | SQL + Visualization fanout completes within 25s. |
| TC-02-004 | Integration | SQL + RAG + Verifier chain produces evidence-backed answer. |
| TC-02-005 | Negative | SQL Agent timeout triggers degraded response with warning. |
| TC-02-006 | Negative | All fanout agents failing still returns a safe degraded answer. |

## 11. Traceability Matrix

| Requirement | Acceptance Criterion | Test Case |
|---|---|---|
| FR-02-001 | AC-02-001, AC-02-002, AC-02-003 | TC-02-001 |
| FR-02-003 | AC-02-001 | TC-02-003 |
| FR-02-006 | AC-02-004 | TC-02-005 |
| FR-02-008 | AC-02-004 | TC-02-005, TC-02-006 |
| NFR-02-001 | AC-02-001, AC-02-002, AC-02-003 | TC-02-001 |
| NFR-02-003 | AC-02-001 | TC-02-003 |

## 12. Open Questions
- OQ-02-001: LangGraph for state machine management in v1?
- OQ-02-002: Split Verifier into SQL-verifier and answer-verifier sub-agents?
- OQ-02-003: Enable async partial-result streaming in v1?
