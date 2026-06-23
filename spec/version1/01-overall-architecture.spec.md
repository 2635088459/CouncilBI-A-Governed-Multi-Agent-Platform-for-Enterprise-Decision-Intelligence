# Spec: Overall Architecture

## 1. Purpose
Define the end-to-end system boundaries, runtime layers, and cross-cutting contracts for the enterprise ChatBI platform.

## 2. Scope
In scope:
- Frontend ChatBI experience layer
- Backend API and orchestration layer
- Multi-agent execution layer
- Structured data and knowledge retrieval layer
- Governance, audit, evaluation, observability layer

Out of scope:
- Multi-tenant billing
- Kubernetes multi-cluster HA
- Enterprise IAM federation beyond project needs

Assumptions:
- All agents are owned by this platform.
- The platform runs behind a single API gateway in v1.

Constraints:
- Only SELECT queries may reach the database.
- Every answer must carry a trace_id.

## 3. Actors
- Business user
- Analyst
- Orchestrator
- SQL Agent
- Visualization Agent
- Analytics Agent
- RAG Agent
- Verifier Agent
- Backend API Service

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-01-001 | The system MUST accept a natural-language question and return a structured answer. |
| FR-01-002 | The answer MUST include at minimum: answer_text, sql_text, table_result, trace_id. |
| FR-01-003 | The system MUST route requests through the Orchestrator before any agent executes. |
| FR-01-004 | All SQL MUST pass through the Guardrail before database execution. |
| FR-01-005 | The system MUST store every request in query history with its trace_id. |
| FR-01-006 | The system MUST support chart output when the result is a time-series or comparison. |
| FR-01-007 | The system MUST support evidence output when a RAG path is activated. |
| FR-01-008 | The system MUST support query replay from history. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01-001 | Core E2E success rate MUST be >= 99.0% measured monthly. |
| NFR-01-002 | Standard query P95 MUST be <= 8s. |
| NFR-01-003 | Advanced analysis P95 MUST be <= 20s. |
| NFR-01-004 | Dangerous SQL interception rate MUST be 100% on known attack patterns. |
| NFR-01-005 | Every final answer MUST be traceable to SQL and evidence source. |
| NFR-01-006 | The system MUST emit structured logs with trace_id on every request. |

## 6. Architecture Decisions
- AD-01-001: Use orchestrator-driven agent collaboration.
- AD-01-002: Use semantic layer before SQL generation.
- AD-01-003: Use guardrail before database execution.
- AD-01-004: Use audit-first observability with trace_id on every span.

## 7. Key Workflows
- Happy path: question → orchestrate → SQL + fanout → verify → respond
- SQL blocked: guardrail rejects → safe error returned → audit logged
- Timeout/degraded: partial results returned with explicit warning
- Low-confidence verifier: response includes risk flag

## 8. API Contracts

Request (POST /api/v1/chat/query):
```
user_id, session_id, question, locale, role
```

Response:
```
answer_text, sql_text, table_result, chart_spec,
evidence_list, confidence, warnings, trace_id
```

Other endpoints:
- GET /api/v1/chat/history
- GET /api/v1/query/{trace_id}
- GET /api/v1/metrics/catalog

## 9. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-01-001 | A valid question returns a response containing trace_id, answer_text, and sql_text. |
| AC-01-002 | A DROP TABLE statement is blocked with error code SQL_DENY_STATEMENT. |
| AC-01-003 | Query history stores every request including failed ones. |
| AC-01-004 | A replayed trace_id returns the same inputs that produced the original answer. |
| AC-01-005 | A request with a low-confidence answer returns a risk warning in the response. |

## 10. Test Plan

| ID | Type | Description |
|---|---|---|
| TC-01-001 | Smoke | Submit a valid question; expect 200 with trace_id. |
| TC-01-002 | Integration | Happy path query → chart → verifier chain. |
| TC-01-003 | Integration | Query → forecasting chain. |
| TC-01-004 | Negative | SQL with DROP TABLE is blocked. |
| TC-01-005 | Negative | Request without auth returns 401. |
| TC-01-006 | Integration | History endpoint returns past queries. |
| TC-01-007 | Integration | Replay by trace_id reconstructs original context. |

## 11. Traceability Matrix

| Requirement | Acceptance Criterion | Test Case |
|---|---|---|
| FR-01-001 | AC-01-001 | TC-01-001 |
| FR-01-003 | AC-01-001 | TC-01-002 |
| FR-01-004 | AC-01-002 | TC-01-004 |
| FR-01-005 | AC-01-003 | TC-01-006 |
| FR-01-008 | AC-01-004 | TC-01-007 |
| NFR-01-004 | AC-01-002 | TC-01-004 |

## 12. Open Questions
- OQ-01-001: Single backend or split service architecture in v1?
- OQ-01-002: Primary vector store: pgvector or Qdrant?
- OQ-01-003: Default forecasting method: ARIMA or Prophet?
