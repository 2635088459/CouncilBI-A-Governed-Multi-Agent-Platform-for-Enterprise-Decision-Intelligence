# Spec v2: Multi-Agent Orchestration

Source design:
- [Chinese design](../../system_design/02-agent-orchestration-design/VERSION2.zh-CN.md)
- [English design](../../system_design/02-agent-orchestration-design/VERSION2.en.md)

## 1. Purpose
Define a service-oriented, traceable, and recoverable Agent orchestration layer. The spec must allow implementation in small red-green units: one route, one agent step, one state transition, or one failure rule at a time.

## 2. Scope
In scope:
- Orchestrator service input/output contract.
- Agent step contract, state persistence, timeout, retry, and degradation rules.
- Redis short-lived state and PostgreSQL trace persistence.
- Worker handoff for asynchronous tasks.

Out of scope:
- Cross-region queue disaster recovery.
- Multi-active LLM provider failover.
- Free-form Agent-to-Agent protocols outside the typed contract.

## 3. Typed Inputs and Outputs

### 3.1 OrchestrationRequest
Required fields:
- `trace_id: str`
- `session_id: str`
- `user_context: UserContext`
- `question: str` length 1..2000
- `semantic_context: dict`
- `deadline_ms: int` where `100 <= deadline_ms <= 60000`

### 3.2 AgentStepInput
Required fields:
- `trace_id: str`
- `step_name: Literal["orchestrator", "sql", "visualization", "analytics", "rag", "verifier"]`
- `attempt: int` where `1 <= attempt <= 3`
- `task_payload: dict`
- `deadline_ms: int`

### 3.3 AgentStepOutput
Required fields:
- `status: Literal["succeeded", "failed", "degraded", "skipped", "timed_out"]`
- `result: dict | null`
- `confidence: float` where `0.0 <= confidence <= 1.0`
- `warnings: list[WarningPayload]`
- `metrics: dict`
- `error: ErrorPayload | null`

## 4. Boundary and Validation Rules
| ID | Rule | Verifier |
|---|---|---|
| VR-02-001 | Every Agent step MUST use idempotency key `trace_id + step_name + attempt`. | Unit test |
| VR-02-002 | SQL Agent MUST complete Guardrail approval before Visualization, Analytics, or RAG steps can run. | State-machine test |
| VR-02-003 | Non-critical Agent failures MUST produce degraded output, not an unhandled exception. | Negative integration test |
| VR-02-004 | If `deadline_ms` is exceeded, the step status MUST be `timed_out` and include `error.code == "AGENT_TIMEOUT"`. | Timeout test |
| VR-02-005 | Orchestrator restart MUST NOT duplicate an already succeeded step with the same idempotency key. | Recovery test |

## 5. Functional Requirements
| ID | Requirement |
|---|---|
| FR-02-001 | Orchestrator MUST classify supported task types into `sql_query`, `chart`, `analytics`, `rag_explanation`, or `verification`. |
| FR-02-002 | Orchestrator MUST persist every Agent step start and finish event in PostgreSQL. |
| FR-02-003 | Orchestrator MUST store in-flight request state in Redis keyed by `trace_id`. |
| FR-02-004 | Visualization, Analytics, and RAG steps MUST run only after SQL result availability. |
| FR-02-005 | Verifier MUST run before final answer assembly. |
| FR-02-006 | Worker handoff MUST create a task id for asynchronous analytics or indexing work. |

## 6. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-02-001 | Orchestrator classification with mock providers MUST complete in P95 <= 150ms over 500 requests. |
| NFR-02-002 | Trace persistence MUST record start and finish events for 100% of executed steps in integration tests. |
| NFR-02-003 | Duplicate step execution rate MUST be 0 for repeated submissions with the same idempotency key. |
| NFR-02-004 | Pyright MUST report 0 errors for Agent contract models and state machine code. |

## 7. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-02-001 | A SQL-only request creates `orchestrator`, `sql`, and `verifier` trace steps. |
| AC-02-002 | A chart request does not start Visualization until SQL step has status `succeeded`. |
| AC-02-003 | A failed RAG step returns final status `degraded` with warning `RAG_UNAVAILABLE` when SQL succeeded. |
| AC-02-004 | A timed-out Agent step stores `AGENT_TIMEOUT` in trace and Redis state. |
| AC-02-005 | Replaying the same idempotency key returns the previous step output without executing the Agent again. |

## 8. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-02-001 | pyright | Validate Agent input/output and task type enums. |
| TC-02-002 | pytest unit | Classify fixed benchmark questions into expected task types. |
| TC-02-003 | pytest state | Assert SQL precedes Visualization/Analytics/RAG. |
| TC-02-004 | pytest integration | Assert trace rows for start and finish events. |
| TC-02-005 | pytest negative | Force RAG failure and assert degraded final output. |
| TC-02-006 | pytest timeout | Force Agent timeout and assert `AGENT_TIMEOUT`. |
| TC-02-007 | pytest recovery | Submit same idempotency key twice and assert one execution. |
| TC-02-008 | benchmark | Measure classification P95 under mock providers. |

## 9. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-02-001 | AC-02-001 | TC-02-002 |
| FR-02-002 | AC-02-001 | TC-02-004 |
| FR-02-003 | AC-02-004 | TC-02-006 |
| FR-02-004 | AC-02-002 | TC-02-003 |
| FR-02-005 | AC-02-001 | TC-02-004 |
| FR-02-006 | AC-02-004 | TC-02-006 |
| NFR-02-001 | AC-02-001 | TC-02-008 |
| NFR-02-002 | AC-02-001 | TC-02-004 |
| NFR-02-003 | AC-02-005 | TC-02-007 |
| NFR-02-004 | AC-02-001 | TC-02-001 |

## 10. First Red-Green Steps
1. Define Agent contract types and task enum.
2. Implement classifier for fixed benchmark questions only.
3. Persist one `orchestrator` step start/finish pair.
4. Add SQL-before-Visualization state guard.

