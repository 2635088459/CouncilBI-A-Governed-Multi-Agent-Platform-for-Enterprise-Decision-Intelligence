# 07 Resilience, Rate Limiting, and Scale

## 1. Why Resilience Matters

Production systems face slow LLM APIs, heavy database queries, traffic spikes, long RAG indexing jobs, and agent failures. Without resilience, one small failure can degrade the whole platform.

## 2. Timeouts

Every layer should have timeouts:

1. API request timeout.
2. Agent step timeout.
3. LLM call timeout.
4. SQL execution timeout.
5. Vector search timeout.

External dependencies should never wait forever.

## 3. Retries

Retry transient network errors, 429 responses with backoff, and temporary 5xx errors.

Do not retry permission errors, guardrail blocks, invalid user input, or missing data.

Retries must use backoff to avoid amplifying failures.

## 4. Circuit Breaker

If an LLM provider repeatedly fails:

1. Count failures.
2. Open the breaker after a threshold.
3. Stop calling that provider briefly.
4. Enter half-open mode to test recovery.
5. Close the breaker when healthy.

This protects the system from repeatedly calling a broken dependency.

## 5. Rate Limiting

Rate limits should apply by:

1. User.
2. Organization.
3. IP.
4. Endpoint.
5. LLM token budget.

Chat and admin endpoints can have different policies.

## 6. Bulkheads

Separate resource pools for:

1. Online user queries and evaluation jobs.
2. RAG indexing and live Q&A.
3. Model calls and database queries.

This prevents offline or heavy workloads from hurting interactive users.

## 7. Async Queue

Use queues for:

1. Large file indexing.
2. Large evaluation runs.
3. Report exports.
4. Long forecasting jobs.
5. Large seed generation.

The API should return a task ID, and the frontend can poll or subscribe to status.

## 8. Load Testing

Run:

1. API load tests.
2. Database query load tests.
3. Mock LLM load tests.

Use mock providers before expensive real-model load tests.

## 9. Degradation

Examples:

1. If RAG fails, return query results with an evidence-unavailable notice.
2. If chart generation fails, return table and text.
3. If LLM summary fails, return structured SQL results.
4. If forecasting fails, return historical trend.
5. If admin dashboard fails, do not block normal queries.

## 10. Implementation Order

1. Add timeouts to external dependencies.
2. Add retry/backoff to LLM and vector search.
3. Implement circuit breakers.
4. Add Redis rate limiting.
5. Move long tasks to queues.
6. Add load-test scripts.
7. Record results in verification docs.
