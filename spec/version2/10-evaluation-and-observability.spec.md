# Spec v2: Evaluation and Observability

Source design:
- [Chinese design](../../system_design/10-evaluation-and-observability/VERSION2.zh-CN.md)
- [English design](../../system_design/10-evaluation-and-observability/VERSION2.en.md)

## 1. Purpose
Define the evaluation and observability gates that constrain the probabilistic parts of the system into an acceptable range before implementation is considered green.

## 2. Scope
In scope:
- Health, readiness, metrics, structured logs, traces, audit events, and eval runner outputs.
- Three-layer validation: pyright, pytest, example/human acceptance.
- Release gate rules for SQL safety and core accuracy regressions.

Out of scope:
- Building a custom APM product.
- Multi-cloud observability federation.
- Replacing human review for business semantics.

## 3. Typed Inputs and Outputs

### 3.1 TraceEvent
Required fields:
- `trace_id: str`
- `service: str`
- `span_name: str`
- `status: Literal["started", "succeeded", "failed", "degraded"]`
- `started_at: datetime`
- `ended_at: datetime | null`
- `latency_ms: int | null`

### 3.2 EvalCase
Required fields:
- `case_id: str`
- `question: str`
- `expected_metric_id: str | null`
- `expected_sql_fragments: list[str]`
- `permission_context: dict`

### 3.3 EvalScore
Required fields:
- `case_id: str`
- `sql_correct: bool`
- `sql_safe: bool`
- `rag_faithful: bool | null`
- `answer_quality_score: float` where `0.0 <= answer_quality_score <= 1.0`

## 4. Boundary and Validation Rules
| ID | Rule | Verifier |
|---|---|---|
| VR-10-001 | Every accepted request MUST emit at least one trace event with `trace_id`. | Integration test |
| VR-10-002 | Logs MUST be JSON and include `trace_id` when request-scoped. | Log test |
| VR-10-003 | `/metrics` MUST expose request count, error count, and latency histogram or summary. | Metrics test |
| VR-10-004 | Release gate MUST fail if SQL safety score is below 1.0 on dangerous SQL fixture. | Eval test |
| VR-10-005 | Human acceptance MUST NOT override failing pyright or pytest gates. | Process checklist |

## 5. Functional Requirements
| ID | Requirement |
|---|---|
| FR-10-001 | Every runtime service MUST expose `/healthz`, `/readyz`, and `/metrics`. |
| FR-10-002 | Backend and Orchestrator MUST write trace events by `trace_id`. |
| FR-10-003 | Query Executor MUST write audit events for allow and deny SQL decisions. |
| FR-10-004 | Eval runner MUST load eval cases and write eval runs, scores, and failures. |
| FR-10-005 | Release gate MUST block deployment on pyright errors. |
| FR-10-006 | Release gate MUST block deployment when pytest fails. |
| FR-10-007 | Release gate MUST block deployment when SQL safety eval score is below 100%. |

## 6. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-10-001 | `/metrics` endpoint P99 MUST be <= 100ms over 100 local requests. |
| NFR-10-002 | Trace lookup by `trace_id` over 10,000 trace events MUST complete P95 <= 250ms locally. |
| NFR-10-003 | Eval runner over 50 mock cases MUST complete in <= 60s locally. |
| NFR-10-004 | Pyright MUST report 0 errors before pytest starts in CI. |

## 7. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-10-001 | A chat query can be inspected by trace id across backend, orchestrator, SQL/audit, and final answer records. |
| AC-10-002 | `/metrics` output includes request count, error count, and latency metric names. |
| AC-10-003 | Eval runner creates one `eval_run` row and one `eval_score` row per case. |
| AC-10-004 | Dangerous SQL fixture score below 1.0 makes release gate fail. |
| AC-10-005 | CI process stops after pyright failure and does not run implementation acceptance. |

## 8. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-10-001 | pyright | Validate trace, eval case, and eval score models. |
| TC-10-002 | pytest integration | Execute one chat query and inspect trace-linked records. |
| TC-10-003 | pytest metrics | Assert `/metrics` required metric names. |
| TC-10-004 | pytest eval | Run eval runner over mock cases and assert rows. |
| TC-10-005 | pytest gate | Dangerous SQL fixture below threshold fails release gate. |
| TC-10-006 | benchmark | Trace lookup P95 over 10,000 trace events. |
| TC-10-007 | process | CI script order asserts pyright runs before pytest. |
| TC-10-008 | human example | Human reviews one successful example for usability and business correctness after machine gates pass. |

## 9. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-10-001 | AC-10-002 | TC-10-003 |
| FR-10-002 | AC-10-001 | TC-10-002 |
| FR-10-003 | AC-10-001 | TC-10-002 |
| FR-10-004 | AC-10-003 | TC-10-004 |
| FR-10-005 | AC-10-005 | TC-10-007 |
| FR-10-006 | AC-10-005 | TC-10-007 |
| FR-10-007 | AC-10-004 | TC-10-005 |
| NFR-10-001 | AC-10-002 | TC-10-003 |
| NFR-10-002 | AC-10-001 | TC-10-006 |
| NFR-10-003 | AC-10-003 | TC-10-004 |
| NFR-10-004 | AC-10-005 | TC-10-007 |

## 10. First Red-Green Steps
1. Define trace and eval models.
2. Add `/metrics` smoke test and minimal endpoint.
3. Persist one trace event by trace id.
4. Add eval runner for one dangerous SQL case.

