# Spec FV-06: Resilience and Load Testing

Source design:
- [Resilience and Scale design](../../../system_design/final-version/en/07-resilience-and-scale.en.md)
- [Final roadmap](../../../system_design/final-version/en/09-final-delivery-roadmap.en.md)

## 1. Purpose
Define distributed-system safeguards for timeouts, retries, circuit breakers, rate limits, queues, degradation, and load testing.

## 2. Scope
In scope:
- Timeout budgets for API, agents, LLM, SQL, and vector search.
- Retry/backoff for transient external dependency failures.
- Circuit breaker, rate limiting, bulkheads, queues, and load-test reporting.

Out of scope:
- Multi-region active-active high availability.
- Chaos engineering platform beyond targeted failure tests.

## 3. Functional Requirements
| ID | Requirement |
|---|---|
| FR-FV06-001 | External dependency calls MUST have configurable timeouts. |
| FR-FV06-002 | LLM and vector calls MUST support bounded retry with backoff for transient failures. |
| FR-FV06-003 | Repeated external dependency failures MUST open a circuit breaker. |
| FR-FV06-004 | API requests MUST be rate-limited by user and organization. |
| FR-FV06-005 | Long-running jobs MUST be executable through an async queue with task status. |
| FR-FV06-006 | Offline evaluation/indexing work MUST not exhaust online chat resources. |
| FR-FV06-007 | The system MUST provide safe degradation for RAG, charting, summarization, and forecasting failures. |
| FR-FV06-008 | Load-test reports MUST include P50, P95, P99, error rate, and test configuration. |

## 4. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-FV06-001 | Timeout failures SHOULD return controlled errors, not stack traces. |
| NFR-FV06-002 | Rate-limit counters SHOULD use Redis or a shared store in multi-replica deployment. |
| NFR-FV06-003 | Mock LLM load tests MUST avoid real provider cost by default. |
| NFR-FV06-004 | Queue status endpoint SHOULD respond P95 <= 250ms locally for 10k tasks. |

## 5. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-FV06-001 | Mock LLM timeout triggers degraded response without crashing chat API. |
| AC-FV06-002 | Repeated provider failures open circuit breaker and stop immediate provider calls. |
| AC-FV06-003 | User/org rate limits return 429 with retry guidance. |
| AC-FV06-004 | Long indexing/eval job returns task id and exposes status. |
| AC-FV06-005 | Load-test artifact includes P50/P95/P99 and error rate. |

## 6. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-FV06-001 | unit | Timeout wrapper returns controlled timeout error. |
| TC-FV06-002 | unit | Retry policy retries transient failures and stops on non-retryable errors. |
| TC-FV06-003 | unit | Circuit breaker opens after threshold and half-opens after cooldown. |
| TC-FV06-004 | integration | Rate limit returns 429 after configured threshold. |
| TC-FV06-005 | integration | Long RAG indexing job returns task id and status transitions. |
| TC-FV06-006 | integration negative | RAG, charting, summarization, and forecasting failures degrade answer instead of failing whole query. |
| TC-FV06-007 | load | Mock LLM/API load test produces latency and error-rate report. |

Implemented test coverage:
- `tests/test_resilience.py`
- `tests/test_llm_provider_gateway.py`
- `tests/test_embedding_vector_rag.py`
- `tests/test_load_testing.py`
- `tests/test_app.py`
- `tests/test_http_app.py`
- `tests/test_worker_handoff.py`
- `tests/test_plan_executor.py`
- `tests/test_summarization.py`

Implemented source modules:
- `src/chatbi/resilience.py`
- `src/chatbi/rate_limit.py`
- `src/chatbi/llm/gateway.py`
- `src/chatbi/embedding_vector_rag.py`
- `src/chatbi/load_testing.py`
- `src/chatbi/application/app.py`
- `src/chatbi/orchestration/worker.py`
- `src/chatbi/orchestration/executor.py`
- `src/chatbi/summarization.py`

Implemented NFR evidence:
- `NFR-FV06-002`: `ChatBIApplication` accepts injectable `RateLimitCounterStore` instances for user and organization counters. The default local implementation is `InMemorySlidingWindowRateLimitStore`; multi-replica deployments can provide a Redis/shared implementation behind the same interface. `tests/test_app.py::test_handle_chat_query_supports_shared_rate_limit_store_across_replicas` verifies shared counter behavior across app replicas.

## 7. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-FV06-001 | AC-FV06-001 | TC-FV06-001 |
| FR-FV06-002 | AC-FV06-001 | TC-FV06-002 |
| FR-FV06-003 | AC-FV06-002 | TC-FV06-003 |
| FR-FV06-004 | AC-FV06-003 | TC-FV06-004 |
| FR-FV06-005 | AC-FV06-004 | TC-FV06-005 |
| FR-FV06-006 | AC-FV06-004 | TC-FV06-005 |
| FR-FV06-007 | AC-FV06-001 | TC-FV06-006 |
| FR-FV06-008 | AC-FV06-005 | TC-FV06-007 |
