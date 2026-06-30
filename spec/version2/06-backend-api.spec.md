# Spec v2: Backend API

Source design:
- [Chinese design](../../system_design/06-backend-api-design/VERSION2.zh-CN.md)
- [English design](../../system_design/06-backend-api-design/VERSION2.en.md)

## 1. Purpose
Define a container-ready Backend API that is the only frontend entry point and the only public boundary for chat, history, catalog, task status, and document indexing.

## 2. Scope
In scope:
- REST endpoints and response envelope.
- PostgreSQL and Redis connection readiness.
- Request validation, error codes, idempotency, and trace propagation.
- Health, readiness, and metrics endpoints.

Out of scope:
- GraphQL.
- Public commercial API billing.
- Direct frontend access to Agent or database services.

## 3. Typed Inputs and Outputs

### 3.1 ApiEnvelope[T]
Required fields:
- `data: T | null`
- `warnings: list[WarningPayload]`
- `error: ErrorPayload | null`
- `trace_id: str | null`
- `request_id: str`

### 3.2 ErrorPayload
Required fields:
- `code: Literal["VALIDATION_ERROR", "SQL_GUARDRAIL_DENIED", "PERMISSION_DENIED", "QUERY_TIMEOUT", "AGENT_PARTIAL_FAILURE", "INTERNAL_ERROR"]`
- `message: str`
- `retryable: bool`

## 4. Boundary and Validation Rules
| ID | Rule | Verifier |
|---|---|---|
| VR-06-001 | Every API response MUST use `ApiEnvelope`. | Contract test |
| VR-06-002 | Controllers MUST NOT execute raw SQL directly. | Import/static test |
| VR-06-003 | Missing or invalid request body MUST return `VALIDATION_ERROR`. | Negative API test |
| VR-06-004 | `/readyz` MUST fail when PostgreSQL or Redis is unavailable. | Runtime test |
| VR-06-005 | Long-running task status MUST be queryable by `task_id`. | API integration test |

## 5. Functional Requirements
| ID | Requirement |
|---|---|
| FR-06-001 | Backend MUST implement `POST /api/v1/chat/query`. |
| FR-06-002 | Backend MUST implement `GET /api/v1/chat/tasks/{task_id}`. |
| FR-06-003 | Backend MUST implement `GET /api/v1/chat/history`. |
| FR-06-004 | Backend MUST implement `GET /api/v1/query/{trace_id}`. |
| FR-06-005 | Backend MUST implement `GET /api/v1/metrics/catalog`. |
| FR-06-006 | Backend MUST implement `GET /healthz`, `GET /readyz`, and `GET /metrics`. |

## 6. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-06-001 | With mock orchestrator, `POST /api/v1/chat/query` P95 MUST be <= 500ms over 100 local requests. |
| NFR-06-002 | History endpoint over 10,000 seeded messages MUST return first page P95 <= 300ms locally. |
| NFR-06-003 | API error responses MUST never include stack traces, database credentials, or raw Secret values. |
| NFR-06-004 | Pyright MUST report 0 errors for API models and route handler signatures. |

## 7. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-06-001 | Valid chat query returns `ApiEnvelope[AnswerPayload]` with `trace_id`. |
| AC-06-002 | Invalid chat query returns envelope with `error.code == "VALIDATION_ERROR"`. |
| AC-06-003 | History endpoint returns records ordered by `created_at desc`. |
| AC-06-004 | Replay endpoint returns 404 or `NOT_FOUND` envelope for unknown trace id. |
| AC-06-005 | Readiness fails when Redis is unavailable. |

## 8. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-06-001 | pyright | Validate API envelope and error code enums. |
| TC-06-002 | pytest API | Valid chat query returns envelope and trace id. |
| TC-06-003 | pytest negative | Invalid body returns validation envelope. |
| TC-06-004 | pytest API | History is ordered and paginated. |
| TC-06-005 | pytest API | Unknown trace id returns not found. |
| TC-06-006 | pytest runtime | Redis outage fails readiness. |
| TC-06-007 | benchmark | Chat query P95 with mock orchestrator. |
| TC-06-008 | security | Error payload does not expose stack trace or credentials. |

## 9. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-06-001 | AC-06-001 | TC-06-002 |
| FR-06-002 | AC-06-001 | TC-06-002 |
| FR-06-003 | AC-06-003 | TC-06-004 |
| FR-06-004 | AC-06-004 | TC-06-005 |
| FR-06-005 | AC-06-001 | TC-06-002 |
| FR-06-006 | AC-06-005 | TC-06-006 |
| NFR-06-001 | AC-06-001 | TC-06-007 |
| NFR-06-002 | AC-06-003 | TC-06-004 |
| NFR-06-003 | AC-06-002 | TC-06-008 |
| NFR-06-004 | AC-06-001 | TC-06-001 |

## 10. First Red-Green Steps
1. Implement envelope and error models.
2. Implement `/healthz` only.
3. Implement `/readyz` with Redis/PostgreSQL dependency checks.
4. Implement `POST /api/v1/chat/query` with mock orchestrator.

