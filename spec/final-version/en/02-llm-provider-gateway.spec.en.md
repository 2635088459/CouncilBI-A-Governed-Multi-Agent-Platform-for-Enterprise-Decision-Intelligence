# Spec FV-02: LLM Provider Gateway

Source design:
- [LLM Provider Gateway design](../../../system_design/final-version/en/03-llm-provider-gateway.en.md)
- [Final roadmap](../../../system_design/final-version/en/09-final-delivery-roadmap.en.md)

## 1. Purpose
Define a controlled, observable, testable abstraction for real LLM API usage across intent classification, SQL generation, answer summarization, evidence reasoning, and evaluation.

## 2. Scope
In scope:
- `LLMClient` interface, provider adapters, mock provider, model routing, prompt versioning.
- Timeout, retry/backoff, token/cost/latency tracking, trace events.
- Safe failure behavior for SQL generation, RAG summarization, and eval judging.

Out of scope:
- Training or fine-tuning custom models.
- Committing provider API keys to repository.

## 3. Functional Requirements
| ID | Requirement |
|---|---|
| FR-FV02-001 | The system MUST define a provider-neutral `LLMClient` interface. |
| FR-FV02-002 | The system MUST include a deterministic mock provider for tests. |
| FR-FV02-003 | Real providers MUST be configured by environment variables or secret manager. |
| FR-FV02-004 | LLM requests MUST include task type, prompt version, user/org context, and trace id. |
| FR-FV02-005 | LLM responses MUST record model, provider, latency, token usage, cost estimate, and finish reason. |
| FR-FV02-006 | SQL generation failure MUST never execute SQL. |
| FR-FV02-007 | Provider calls MUST support timeout and bounded retry with backoff. |
| FR-FV02-008 | All LLM calls MUST emit observability events. |
| FR-FV02-009 | Orchestrator integration MUST accept an injected `LLMClient` and MUST NOT depend directly on provider SDKs. |
| FR-FV02-010 | Final answer synthesis MUST pass the user question, safe SQL, bounded table rows, and bounded evidence snippets to the LLM gateway before producing a natural-language answer when an `LLMClient` is configured. |
| FR-FV02-011 | Answer synthesis MUST have a deterministic grounded fallback when no LLM client is configured or the provider fails. |
| FR-FV02-012 | Unsupported or off-domain user text MUST NOT fall through to default demo SQL generation or answer synthesis. |
| FR-FV02-013 | Mock and fallback answer synthesis MUST honor the user question and MUST NOT infer an unrelated metric only because rows contain that value. |
| FR-FV02-014 | Answer synthesis MUST ground domain-specific wording in the actual returned table schema, so support-ticket evidence cannot override revenue rows and revenue evidence cannot override support-ticket rows. |
| FR-FV02-015 | Docker runtime configuration MUST pass LLM provider variables, including optional OpenAI-compatible provider settings, into backend and worker services without hardcoding secrets. |

## 4. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-FV02-001 | Mock provider tests MUST be deterministic and network-free. |
| NFR-FV02-002 | Provider timeout MUST be configurable per task type. |
| NFR-FV02-003 | Cost tracking MUST be aggregatable by user, organization, task type, and day. |
| NFR-FV02-004 | Provider errors MUST be sanitized before returning to end users. |

## 5. Contracts
### 5.1 LLMRequest
Required fields:
- `task_type: str`
- `prompt_version: str`
- `messages: list[dict]`
- `model_policy: dict`
- `temperature: float`
- `max_tokens: int`
- `user_id: str`
- `org_id: str`
- `trace_id: str`

### 5.2 LLMResponse
Required fields:
- `text: str`
- `model_name: str`
- `provider: str`
- `prompt_tokens: int`
- `completion_tokens: int`
- `total_tokens: int`
- `estimated_cost: float`
- `latency_ms: int`
- `finish_reason: str`
- `safety_flags: list[str]`

### 5.3 Observability Event Metadata
Every completed LLM trace event MUST include:
- `provider`
- `model`
- `latency_ms`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `estimated_cost`
- `finish_reason`
- `attempts`

Provider failure events MUST include a sanitized `error` value and MUST NOT expose API keys, raw provider payloads, or low-level SDK exception details.

### 5.4 Runtime Configuration
Real provider adapters MUST read secrets from environment variables or a secret manager. The baseline OpenAI-compatible adapter uses:
- `CHATBI_LLM_PROVIDER` to select `mock` or `openai`; default is `mock`.
- `CHATBI_LLM_MODEL` to select the route model; default is `mock-chatbi-small` for `mock` and `gpt-4o-mini` for `openai` when no model override is provided.
- `CHATBI_LLM_TIMEOUT_MS` to configure the task timeout; default is `1000`.
- `CHATBI_LLM_MAX_RETRIES` to configure bounded retry; default is `1`.
- `CHATBI_LLM_BACKOFF_MS` to configure retry backoff; default is `25`.
- `OPENAI_API_KEY` for the provider secret.
- `OPENAI_BASE_URL` for optional endpoint override.
- `OPENAI_MODEL` for the optional smoke-test model override.

Missing required provider secrets MUST fail initialization before any network call is attempted.

## 6. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-FV02-001 | Existing agent workflows can run using the mock provider without network access. |
| AC-FV02-002 | When a real API key is configured, a smoke test can call the configured provider. |
| AC-FV02-003 | Each LLM call is visible in observability with token and latency metadata. |
| AC-FV02-004 | Timeout or provider failure returns a safe degraded response. |
| AC-FV02-005 | SQL generation provider failure does not reach SQL execution. |
| AC-FV02-006 | Cost records can be aggregated by user, organization, task type, and day. |
| AC-FV02-007 | A support-ticket business question can be answered from SQL rows and document evidence passed through the `answer_synthesis` LLM task. |
| AC-FV02-008 | A prompt such as `hello` returns an unsupported-question response without SQL execution, revenue rows, or answer synthesis. |
| AC-FV02-009 | A mixed prompt that returns revenue rows does not produce support-ticket wording or support-ticket evidence. |
| AC-FV02-010 | Local Docker can stay on mock by default and can switch to OpenAI-compatible provider by setting `CHATBI_LLM_PROVIDER=openai` plus `OPENAI_API_KEY`. |

## 7. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-FV02-001 | unit | Mock provider returns deterministic output and token counts. |
| TC-FV02-002 | unit | Model router selects configured model by task type. |
| TC-FV02-003 | unit negative | Missing API key rejects real provider initialization. |
| TC-FV02-004 | integration | Orchestrator uses `LLMClient` instead of direct SDK calls. |
| TC-FV02-005 | integration negative | SQL generation timeout prevents SQL execution. |
| TC-FV02-006 | observability | LLM call emits trace event with provider, model, latency, and tokens. |
| TC-FV02-007 | optional smoke | Real provider smoke test runs only when provider key is present. |
| TC-FV02-008 | unit | Cost store aggregates token and estimated-cost records by user, organization, task type, and day. |
| TC-FV02-009 | unit | Runtime config builds the mock gateway by default and rejects unsupported providers. |
| TC-FV02-010 | integration | Orchestrator sends safe SQL, returned rows, and evidence citations to `answer_synthesis`. |
| TC-FV02-011 | unit | Runtime config routes both `sql_generation` and `answer_synthesis` through the configured provider. |
| TC-FV02-012 | integration negative | Unsupported text is rejected before SQL generation and before answer synthesis. |
| TC-FV02-013 | unit | Mock answer synthesis only answers highest-revenue questions when the user question requests that metric. |
| TC-FV02-014 | integration | Mixed revenue/support prompt with revenue rows does not attach support-ticket answer text or evidence. |
| TC-FV02-015 | config | Docker Compose wires LLM provider and OpenAI-compatible environment variables to backend and worker. |

Implemented test coverage:
- `tests/test_llm_provider_gateway.py`
- `tests/test_simple_orchestrator.py`

## 8. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-FV02-001 | AC-FV02-001 | TC-FV02-004 |
| FR-FV02-002 | AC-FV02-001 | TC-FV02-001 |
| FR-FV02-003 | AC-FV02-002 | TC-FV02-003, TC-FV02-007 |
| FR-FV02-004 | AC-FV02-003 | TC-FV02-006 |
| FR-FV02-005 | AC-FV02-003 | TC-FV02-006 |
| FR-FV02-006 | AC-FV02-005 | TC-FV02-005 |
| FR-FV02-007 | AC-FV02-004 | TC-FV02-005 |
| FR-FV02-008 | AC-FV02-003 | TC-FV02-006 |
| FR-FV02-009 | AC-FV02-001, AC-FV02-005 | TC-FV02-004, TC-FV02-005 |
| FR-FV02-010 | AC-FV02-007 | TC-FV02-010 |
| FR-FV02-011 | AC-FV02-004, AC-FV02-007 | TC-FV02-010, TC-FV02-011 |
| FR-FV02-012 | AC-FV02-008 | TC-FV02-012 |
| FR-FV02-013 | AC-FV02-008 | TC-FV02-013 |
| FR-FV02-014 | AC-FV02-009 | TC-FV02-014 |
| FR-FV02-015 | AC-FV02-010 | TC-FV02-015 |
| NFR-FV02-003 | AC-FV02-006 | TC-FV02-008 |
| NFR-FV02-002 | AC-FV02-004 | TC-FV02-002, TC-FV02-009 |
