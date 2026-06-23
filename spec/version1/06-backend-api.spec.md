# Spec: Backend API

## 1. Purpose
Define the stable API surface that connects the frontend, agents, and data services with unified contracts, error handling, and observability.

## 2. Scope
In scope:
- Session and query APIs
- Catalog, history, audit, and evaluation APIs
- Error model, idempotency, pagination, rate limiting

Out of scope:
- Public API monetization platform
- GraphQL in v1

Assumptions:
- v1 uses a single FastAPI or equivalent backend service.
- JWT is the authentication mechanism.

Constraints:
- All responses MUST use the unified envelope schema.
- Every request MUST carry X-Trace-Id.

## 3. API Groups
- Chat/query
- History/replay
- Catalog (metrics, datasets)
- Evaluation/audit
- Health/config

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-06-001 | The API MUST accept a question and return a structured answer via POST /api/v1/chat/query. |
| FR-06-002 | The API MUST return query history via GET /api/v1/chat/history with cursor pagination. |
| FR-06-003 | The API MUST return a trace detail by trace_id via GET /api/v1/query/{trace_id}. |
| FR-06-004 | The API MUST serve the metric catalog via GET /api/v1/metrics/catalog. |
| FR-06-005 | The API MUST return structured error codes with user-safe messages on failure. |
| FR-06-006 | The API MUST support Idempotency-Key on POST /api/v1/chat/query with a 60s window. |
| FR-06-007 | The API MUST write an audit record for every request. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-06-001 | /chat/query P95 MUST be <= 8s. |
| NFR-06-002 | /chat/history P95 MUST be <= 500ms. |
| NFR-06-003 | All responses MUST use the unified envelope: code, message, data, trace_id, warnings, timestamp. |
| NFR-06-004 | Per-user rate limits MUST be enforced. |

## 6. Unified Response Envelope

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "trace_id": "trc_xxx",
  "warnings": [],
  "timestamp": "2026-06-16T12:00:00Z"
}
```

## 7. Error Codes

| Code | Meaning |
|---|---|
| AUTH_UNAUTHORIZED | Missing or invalid token |
| AUTH_FORBIDDEN | Valid token but insufficient role |
| REQ_INVALID_ARGUMENT | Bad request payload |
| SQL_GUARDRAIL_BLOCKED | SQL denied by policy |
| QUERY_TIMEOUT | Downstream query timeout |
| AGENT_PARTIAL_FAILURE | Some agents failed; degraded response |
| INTERNAL_ERROR | Unexpected server error |

## 8. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-06-001 | POST /api/v1/chat/query returns 200 with trace_id and answer fields for a valid question. |
| AC-06-002 | Same request with same Idempotency-Key within 60s returns the cached result. |
| AC-06-003 | A request without Authorization returns AUTH_UNAUTHORIZED. |
| AC-06-004 | GET /api/v1/chat/history returns paginated results with cursor. |
| AC-06-005 | A query with guardrail block returns SQL_GUARDRAIL_BLOCKED in the error code field. |
| AC-06-006 | Every response (success and error) contains trace_id. |

## 9. Test Plan

| ID | Type | Description |
|---|---|---|
| TC-06-001 | Unit | Payload validator rejects missing required fields. |
| TC-06-002 | Unit | Error-code mapper returns correct HTTP status per code. |
| TC-06-003 | Integration | Full query path returns unified envelope with trace_id. |
| TC-06-004 | Integration | History endpoint returns cursor-paginated results. |
| TC-06-005 | Negative | Request without token returns 401 AUTH_UNAUTHORIZED. |
| TC-06-006 | Negative | Duplicate Idempotency-Key returns same response within TTL. |
| TC-06-007 | Performance | /chat/query P95 <= 8s under expected load. |

## 10. Traceability Matrix

| Requirement | Acceptance Criterion | Test Case |
|---|---|---|
| FR-06-001 | AC-06-001 | TC-06-003 |
| FR-06-002 | AC-06-004 | TC-06-004 |
| FR-06-005 | AC-06-005 | TC-06-005 |
| FR-06-006 | AC-06-002 | TC-06-006 |
| FR-06-007 | AC-06-006 | TC-06-003 |
| NFR-06-001 | AC-06-001 | TC-06-007 |
| NFR-06-003 | AC-06-006 | TC-06-003 |

## 11. Open Questions
- OQ-06-001: Split Query API and Agent API services?
- OQ-06-002: Enable SSE streaming in v1?
- OQ-06-003: Centralized audit via gateway plugin?
