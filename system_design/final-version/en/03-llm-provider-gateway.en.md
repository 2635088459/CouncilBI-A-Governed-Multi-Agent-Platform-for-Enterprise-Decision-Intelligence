# 03 LLM Provider Gateway

## 1. Why the System Needs a Gateway

Production LLM usage is more than calling an SDK. The platform must handle model selection, timeouts, retries, token usage, cost, prompt versions, provider changes, and observability.

The LLM Provider Gateway is the single controlled interface for model calls.

## 2. Responsibilities

The gateway handles:

1. Unified request format.
2. Unified response format.
3. Model routing.
4. Prompt template/version management.
5. Timeouts, retries, and circuit breakers.
6. Token and cost tracking.
7. Trace and log emission.
8. Safety filtering and sensitive-data handling.

## 3. Internal Request Shape

```text
LLMRequest
- task_type: intent_classification | sql_generation | answer_synthesis | answer_summary | evidence_reasoning
- prompt_version
- messages
- model_policy
- temperature
- max_tokens
- user_id
- org_id
- trace_id
```

## 4. Internal Response Shape

```text
LLMResponse
- text
- model_name
- provider
- prompt_tokens
- completion_tokens
- total_tokens
- estimated_cost
- latency_ms
- finish_reason
- safety_flags
- raw_response_ref
```

The system needs more than the text answer. It must also know which model ran, how slow it was, how much it cost, and whether it produced risk signals.

## 5. Routing Strategy

Different tasks can use different models:

1. Intent classification: cheaper and faster model.
2. SQL generation: stronger instruction-following model.
3. Answer synthesis: grounded model call that receives bounded SQL rows and
   evidence snippets, and must answer only from that context.
4. Evaluation judge: separate judge model or rule/model hybrid.

Model names should be configuration-driven, not hard-coded.

For explanation questions such as "why" or "explain", answer synthesis must use
the provided evidence snippets and cite their anchors when available. It must
not return a generic trend summary when relevant evidence was supplied.

## 6. Failure Handling

Recommended behavior:

1. Set timeout for each model call.
2. Retry transient network and 5xx errors with backoff.
3. Trigger a circuit breaker after repeated failures.
4. Never execute SQL if SQL generation fails.
5. Return structured data if summary generation fails.
6. Emit observability events for every failure.

## 7. Cost Control

Track token and cost by:

1. Request.
2. User.
3. Organization.
4. Task type.
5. Day and month.

When budget is tight, the system can downgrade models, limit context length, rate-limit users, or alert admins.

## 8. Implementation Order

1. Define an `LLMClient` interface.
2. Implement a real provider adapter.
3. Keep a fake/mock adapter for tests.
4. Route orchestrator model calls through the gateway.
5. Add token/cost logging.
6. Add failure and degradation tests.
7. Add grounded answer-synthesis tests that prove SQL rows and RAG evidence are
   passed through the gateway and used in the final answer.
