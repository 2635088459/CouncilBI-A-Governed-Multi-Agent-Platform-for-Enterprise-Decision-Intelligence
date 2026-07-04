# 08 Security, Observability, and Admin Console

## 1. Why Spec 10 Must Be Admin-Only

Spec 10 includes evaluation results, traces, metrics, release gates, and runtime logs. These are valuable but sensitive.

They can include user questions, SQL, stack traces, model call information, table names, field names, and security policy events.

Therefore, these capabilities must sit behind admin permissions.

## 2. Admin Console Scope

The admin console should be reachable from the React + Vite frontend and show:

1. System health: latency, error rate, queue length.
2. LLM health: calls, failures, tokens, cost.
3. SQL safety: blocked queries, risky patterns, slow queries.
4. RAG health: retrieval hit rate and indexing status.
5. Evaluation: eval results, failed cases, quality trends.
6. Release Gate: whether a release is allowed.
7. Audit: user behavior, security events, permission changes.

## 3. Observability Signals

### Logs

Structured logs should include:

1. `timestamp`
2. `level`
3. `trace_id`
4. `user_id`
5. `org_id`
6. `event_type`
7. `message`
8. `metadata`

Sensitive content must be masked.

### Metrics

Core metrics:

1. Request latency.
2. Request error rate.
3. LLM latency.
4. LLM token usage.
5. SQL guardrail block count.
6. RAG hit rate.
7. Evaluation pass rate.
8. Release gate status.

### Traces

Each chat query should show:

1. API received.
2. Auth checked.
3. Orchestrator planned.
4. SQL generated.
5. Guardrail checked.
6. DB executed.
7. RAG searched.
8. Answer summarized.
9. Response returned.

## 4. Security Audit

Audit:

1. Login success and failure.
2. Permission changes.
3. Admin access to trace/eval/audit.
4. SQL guardrail blocks.
5. Sensitive field access.
6. Model provider config changes.
7. Release gate override or forced release.

## 5. PII and Sensitive Data

Rules:

1. Never log plaintext passwords or tokens.
2. Mask sensitive user questions before logging.
3. Mask sensitive SQL result fields by permission.
4. Avoid unnecessary personal data in prompts.
5. Protect report exports with authorization checks.

## 6. Relationship to Spec 10

Spec 10 already provides the foundation:

1. Evaluation repository.
2. Runtime metrics.
3. Trace events.
4. Release gate.
5. Evaluation report.
6. Quality dashboard.

The final version adds admin permissions, `org_id` scoping, admin UI rendering, and integration with OpenTelemetry/Prometheus/Grafana or equivalent tools.

## 7. Implementation Order

1. Mark observability/eval/release-gate APIs as admin-only.
2. Add user/org context to logs and traces.
3. Mask sensitive fields.
4. Add admin audit events.
5. Build Admin Console views.
6. Connect metrics dashboards.
7. Add authorization and security tests.

## 8. Current Verification Addendum

The React frontend includes an Admin tab wired to
`/api/v2/admin/observability/summary`. The UI must send only browser-safe
configuration such as `VITE_API_BASE_URL`; backend-only secrets and database
URLs must stay out of the frontend source and Docker runtime.
