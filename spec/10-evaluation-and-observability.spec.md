# Spec: Evaluation and Observability

## 1. Purpose
Define the offline evaluation, online monitoring, alerting, replay, and release-gate systems that ensure platform quality.

## 2. Scope
In scope:
- Offline benchmark evaluation (SQL accuracy, safety, routing, RAG faithfulness)
- Online SLI/SLO monitoring
- Trace, log, and metrics collection
- Alert rules and incident response
- Replay and root-cause analysis
- Release gate policy

Out of scope:
- Custom enterprise APM platform build
- Multi-cloud observability governance

Assumptions:
- Traces are written synchronously during request handling.
- Benchmark suite is maintained and updated alongside metric definitions.

Constraints:
- High-risk SQL miss-interception rate MUST be exactly 0.
- Every request MUST have a trace in the observability store.

## 3. Key SLOs

| SLO ID | Metric | Target |
|---|---|---|
| SLO-10-001 | Monthly E2E success rate | >= 99.0% |
| SLO-10-002 | /chat/query P95 latency | <= 8s |
| SLO-10-003 | High-risk SQL miss rate | = 0 |
| SLO-10-004 | unsupported_claim_rate | <= 2% |

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-10-001 | The system MUST run offline evaluation against a benchmark suite on each release candidate. |
| FR-10-002 | The evaluation MUST score SQL accuracy, SQL safety, agent routing, and RAG faithfulness. |
| FR-10-003 | A release candidate MUST be blocked if any SLO threshold is violated on the benchmark. |
| FR-10-004 | The system MUST emit one trace per request with defined span names. |
| FR-10-005 | Alert rules MUST fire on E2E error rate > 2% sustained for 10 minutes. |
| FR-10-006 | Alert rules MUST fire on /chat/query P95 exceeding SLO for 15 minutes. |
| FR-10-007 | The system MUST support replay of a past request by trace_id. |
| FR-10-008 | Evaluation reports MUST include overall_score, metric_breakdown, and failed_cases. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-10-001 | Trace writes MUST NOT add more than 10ms to request latency. |
| NFR-10-002 | Alert false-positive rate MUST be controllable to avoid alert fatigue. |
| NFR-10-003 | Sensitive data in logs MUST be masked. |

## 6. Trace Span Standards

```
request_received, orchestration_planned, sql_generated,
sql_guardrail_checked, rag_retrieved, analytics_done,
verifier_done, response_sent
```

## 7. Evaluation Metrics

| Dimension | Metric |
|---|---|
| SQL Accuracy | Table, field, filter, aggregation correctness |
| SQL Safety | Dangerous-SQL interception rate |
| Agent Routing | Correct agent-combination rate |
| RAG Faithfulness | citation_coverage, unsupported_claim_rate |
| Latency | E2E P50/P95/P99 |

## 8. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-10-001 | A release that fails SQL safety threshold is blocked by the gate. |
| AC-10-002 | An E2E error rate > 2% for 10 min fires an alert. |
| AC-10-003 | A replay by trace_id returns the original inputs, SQL, and evidence used. |
| AC-10-004 | All active SLOs are visible in the quality dashboard. |
| AC-10-005 | Log records do not contain unmasked PII. |

## 9. Test Plan

| ID | Type | Description |
|---|---|---|
| TC-10-001 | Unit | Scoring functions compute correct values for known inputs. |
| TC-10-002 | Integration | Full benchmark suite runs and produces pass/fail report. |
| TC-10-003 | Integration | Replay of a past trace_id reconstructs the original context. |
| TC-10-004 | Negative | Evaluation failure (SQL safety) blocks release gate. |
| TC-10-005 | Negative | Simulated error spike triggers alert within 10 minutes. |
| TC-10-006 | Compliance | PII field values are absent from all log records. |

## 10. Traceability Matrix

| Requirement | Acceptance Criterion | Test Case |
|---|---|---|
| FR-10-001 | AC-10-001 | TC-10-002 |
| FR-10-003 | AC-10-001 | TC-10-004 |
| FR-10-004 | AC-10-003 | TC-10-003 |
| FR-10-005 | AC-10-002 | TC-10-005 |
| FR-10-007 | AC-10-003 | TC-10-003 |
| NFR-10-003 | AC-10-005 | TC-10-006 |
| SLO-10-003 | AC-10-001 | TC-10-004 |

## 11. Open Questions
- OQ-10-001: Benchmark suite refresh cadence?
- OQ-10-002: Default trace sampling rate in production?
- OQ-10-003: Automated RCA clustering for recurring failures?
