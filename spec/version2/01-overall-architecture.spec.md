# Spec v2: Overall Architecture

Source design:
- [Chinese design](../../system_design/01-overall-architecture/VERSION2.zh-CN.md)
- [English design](../../system_design/01-overall-architecture/VERSION2.en.md)

## 1. Purpose
Define the deployable v2 ChatBI runtime architecture before implementation. This spec is the source of truth for service boundaries, cross-service contracts, environment behavior, and the first verifiable end-to-end slice.

## 2. Scope
In scope:
- Frontend Web, Backend API, Agent Orchestrator, Query Executor, RAG Indexer, Worker, PostgreSQL, Redis, and vector store boundaries.
- Docker Compose local runtime and Kubernetes production runtime contracts.
- Cross-service trace, health, readiness, and metrics requirements.
- Frontend-backend request/response envelope.

Out of scope:
- Multi-cluster Kubernetes HA.
- Cloud-provider-specific managed database provisioning.
- Enterprise IAM federation beyond a typed user context.
- Billing, tenant metering, and quota marketplace features.

## 3. Actors
- Business User
- Frontend Web App
- Backend API Service
- Agent Orchestrator
- Query Executor
- RAG Indexer
- Async Worker
- PostgreSQL
- Redis
- Kubernetes Runtime

## 4. Typed Inputs and Outputs

### 4.1 ChatQueryRequest
Type gate: Pydantic model or TypedDict.

Required fields:
- `request_id: str` matching `^req_[A-Za-z0-9_-]{8,64}$`
- `session_id: str` matching `^ses_[A-Za-z0-9_-]{8,64}$`
- `user_id: str` length 1..128
- `role: Literal["business_user", "analyst", "admin"]`
- `locale: Literal["en", "zh-CN"]`
- `question: str` length 1..2000

### 4.2 ChatQueryResponse
Type gate: Pydantic model or TypedDict.

Required fields:
- `trace_id: str` matching `^tr_[A-Za-z0-9_-]{8,64}$`
- `data: AnswerPayload | null`
- `warnings: list[WarningPayload]`
- `error: ErrorPayload | null`
- `request_id: str`

### 4.3 AnswerPayload
Required fields:
- `answer_text: str`
- `table_result: TableResult | null`
- `chart_spec: dict | null`
- `evidence_list: list[EvidenceItem]`
- `confidence: float` where `0.0 <= confidence <= 1.0`

## 5. Boundary and Validation Rules
| ID | Rule | Verifier |
|---|---|---|
| VR-01-001 | Frontend MUST call only Backend API routes; it MUST NOT call database, Redis, vector store, or Agent services directly. | Static config test + API client unit test |
| VR-01-002 | Every accepted request MUST have exactly one `trace_id`, and all downstream records MUST reuse it unchanged. | Integration test |
| VR-01-003 | Runtime services MUST expose `/healthz`, `/readyz`, and `/metrics`. | HTTP smoke test |
| VR-01-004 | The Backend API MUST reject missing `request_id`, `session_id`, `user_id`, `role`, `locale`, or `question` with `VALIDATION_ERROR`. | Negative API test |
| VR-01-005 | The Query Executor MUST be reachable only through Backend API or Orchestrator code paths. | Architecture import/dependency test |

## 6. Functional Requirements
| ID | Requirement |
|---|---|
| FR-01-001 | Docker Compose MUST define runnable services for frontend, backend API, PostgreSQL, Redis, and worker. |
| FR-01-002 | Backend API MUST create and return a `trace_id` for every valid chat query. |
| FR-01-003 | Backend API MUST persist request metadata and final status to PostgreSQL using `trace_id`. |
| FR-01-004 | Backend API MUST read `DATABASE_URL`, `REDIS_URL`, and `VECTOR_STORE_URL` from environment variables. |
| FR-01-005 | Kubernetes manifests MUST define Deployment or equivalent workload specs for frontend, backend API, orchestrator/worker, and Redis dependency wiring. |
| FR-01-006 | Readiness MUST fail when PostgreSQL is unreachable. |

## 7. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-01-001 | `POST /api/v1/chat/query` with a mock orchestrator MUST have P95 latency <= 500ms over 100 requests, 10 concurrent clients, local Docker runtime. |
| NFR-01-002 | `/healthz` and `/readyz` MUST each respond in <= 100ms P99 over 100 local requests. |
| NFR-01-003 | Structured logs for accepted requests MUST include `trace_id`, `request_id`, `service`, `event`, and `level` in 100% of sampled records. |
| NFR-01-004 | Pyright MUST report 0 errors for all public architecture contract models. |

## 8. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-01-001 | A valid request returns status 200 with `trace_id`, `request_id`, and a valid response envelope. |
| AC-01-002 | A request missing `question` returns status 422 or 400 with `error.code == "VALIDATION_ERROR"`. |
| AC-01-003 | When PostgreSQL is unavailable, `/readyz` returns non-2xx and `/healthz` still returns 2xx if the process is alive. |
| AC-01-004 | A persisted request row can be selected by the returned `trace_id`. |
| AC-01-005 | Frontend runtime configuration contains only Backend API URL, not database, Redis, vector, or Agent URLs. |

## 9. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-01-001 | pyright | Validate request/response contract types and required fields. |
| TC-01-002 | pytest API | Submit a valid chat query with mock orchestrator; assert envelope and trace id. |
| TC-01-003 | pytest negative | Submit request without `question`; assert validation error. |
| TC-01-004 | pytest integration | Assert request metadata is stored in PostgreSQL by trace id. |
| TC-01-005 | pytest runtime | Stop or mock PostgreSQL outage; assert readiness failure. |
| TC-01-006 | pytest config | Assert frontend config exposes Backend API URL only. |
| TC-01-007 | benchmark | Measure chat query P95 with mock orchestrator under 100 requests / 10 concurrency. |
| TC-01-008 | human example | Run one local example query and review whether the returned error/warning text is actionable. |

## 10. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-01-001 | AC-01-001 | TC-01-002 |
| FR-01-002 | AC-01-001 | TC-01-002 |
| FR-01-003 | AC-01-004 | TC-01-004 |
| FR-01-004 | AC-01-003 | TC-01-005 |
| FR-01-005 | AC-01-005 | TC-01-006 |
| FR-01-006 | AC-01-003 | TC-01-005 |
| NFR-01-001 | AC-01-001 | TC-01-007 |
| NFR-01-002 | AC-01-003 | TC-01-005 |
| NFR-01-003 | AC-01-004 | TC-01-004 |
| NFR-01-004 | AC-01-001 | TC-01-001 |

## 11. First Red-Green Steps
1. Contract only: define `ChatQueryRequest`, `ChatQueryResponse`, and `ErrorPayload`; run pyright red then green.
2. One endpoint: implement `POST /api/v1/chat/query` with mock orchestrator; make TC-01-002 green.
3. One persistence path: write request metadata by `trace_id`; make TC-01-004 green.
4. One readiness rule: fail readiness on database outage; make TC-01-005 green.

