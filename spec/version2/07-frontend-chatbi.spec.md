# Spec v2: Frontend ChatBI

Source design:
- [Chinese design](../../system_design/07-frontend-chatbi-design/VERSION2.zh-CN.md)
- [English design](../../system_design/07-frontend-chatbi-design/VERSION2.en.md)

## 1. Purpose
Define the frontend behavior and integration contract for the v2 ChatBI Web application. The frontend must be testable without a real backend by using typed API fixtures and must integrate with the real Backend API through the same client contract.

## 2. Scope
In scope:
- Chat workspace, history panel, metric catalog, task status, and error boundary.
- API client envelope parsing and trace display.
- Docker/Kubernetes runtime configuration for API base URL.
- Frontend observability fields.

Out of scope:
- Native mobile app.
- Drag-and-drop BI dashboard builder.
- Direct database, Redis, vector store, or Agent access.

## 3. Typed Inputs and Outputs

### 3.1 FrontendRuntimeConfig
Required fields:
- `api_base_url: str`
- `environment: Literal["dev", "staging", "prod"]`
- `locale_default: Literal["en", "zh-CN"]`

Forbidden fields:
- `database_url`
- `redis_url`
- `vector_store_url`
- `agent_url`

### 3.2 UiAnswerState
Required fields:
- `status: Literal["idle", "submitting", "running", "partial", "failed", "completed"]`
- `trace_id: str | null`
- `answer_text: str | null`
- `table_result: dict | null`
- `chart_spec: dict | null`
- `evidence_list: list[dict]`
- `warnings: list[dict]`
- `error_code: str | null`

## 4. Boundary and Validation Rules
| ID | Rule | Verifier |
|---|---|---|
| VR-07-001 | API client MUST call only paths under `api_base_url`. | Unit test |
| VR-07-002 | API client MUST parse all responses through `ApiEnvelope`. | Unit test |
| VR-07-003 | `trace_id` MUST be visible and copyable when present. | Component test |
| VR-07-004 | `AGENT_PARTIAL_FAILURE` MUST render a warning state, not a full failure state. | Component test |
| VR-07-005 | Runtime config MUST NOT contain database, Redis, vector, or Agent URLs. | Config test |

## 5. Functional Requirements
| ID | Requirement |
|---|---|
| FR-07-001 | Chat Workspace MUST submit a question to `POST /api/v1/chat/query`. |
| FR-07-002 | Chat Workspace MUST render answer text, table result, chart spec, evidence list, warnings, and trace id when provided. |
| FR-07-003 | History Panel MUST fetch and render records from `GET /api/v1/chat/history`. |
| FR-07-004 | Metric Catalog MUST fetch and render records from `GET /api/v1/metrics/catalog`. |
| FR-07-005 | Task Status MUST render queued, running, partial, failed, and completed states. |
| FR-07-006 | Error Boundary MUST render `VALIDATION_ERROR`, `SQL_GUARDRAIL_DENIED`, and `INTERNAL_ERROR` with user-actionable messages. |

## 6. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-07-001 | With mocked API fixtures, first meaningful render MUST complete in <= 2000ms on local test runner. |
| NFR-07-002 | Submit button click to loading state transition MUST complete in <= 100ms in component test. |
| NFR-07-003 | Frontend logs for query submit MUST include `request_id`, `session_id`, and `event`. |
| NFR-07-004 | Type checker MUST report 0 errors for API client and UI state models. |

## 7. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-07-001 | Submitting "show monthly revenue" calls `/api/v1/chat/query` once with request id and session id. |
| AC-07-002 | Successful fixture renders answer text, table, chart container, evidence list, warning list, and trace id. |
| AC-07-003 | Partial failure fixture renders warning state and keeps available table/chart data visible. |
| AC-07-004 | SQL denial fixture renders safety reason and retry suggestion. |
| AC-07-005 | Runtime config test fails if forbidden backend infrastructure URLs are present. |

## 8. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-07-001 | type check | Validate frontend runtime config, API client, and UI state types. |
| TC-07-002 | component | Submit question and assert API call payload. |
| TC-07-003 | component | Render successful answer fixture. |
| TC-07-004 | component | Render partial failure fixture as warning state. |
| TC-07-005 | component | Render SQL Guardrail denial fixture. |
| TC-07-006 | config | Assert forbidden URLs are absent. |
| TC-07-007 | performance | Measure first render and click-to-loading thresholds. |
| TC-07-008 | human example | Review one successful answer screen for usability and business clarity. |

## 9. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-07-001 | AC-07-001 | TC-07-002 |
| FR-07-002 | AC-07-002 | TC-07-003 |
| FR-07-003 | AC-07-002 | TC-07-003 |
| FR-07-004 | AC-07-002 | TC-07-003 |
| FR-07-005 | AC-07-003 | TC-07-004 |
| FR-07-006 | AC-07-004 | TC-07-005 |
| NFR-07-001 | AC-07-002 | TC-07-007 |
| NFR-07-002 | AC-07-001 | TC-07-007 |
| NFR-07-003 | AC-07-001 | TC-07-002 |
| NFR-07-004 | AC-07-005 | TC-07-001 |

## 10. First Red-Green Steps
1. Define API client envelope parser with fixtures.
2. Implement submit button to loading transition.
3. Render successful answer fixture.
4. Render SQL Guardrail denial fixture.

