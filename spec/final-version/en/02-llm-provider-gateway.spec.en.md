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

## 6. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-FV02-001 | Existing agent workflows can run using the mock provider without network access. |
| AC-FV02-002 | When a real API key is configured, a smoke test can call the configured provider. |
| AC-FV02-003 | Each LLM call is visible in observability with token and latency metadata. |
| AC-FV02-004 | Timeout or provider failure returns a safe degraded response. |
| AC-FV02-005 | SQL generation provider failure does not reach SQL execution. |

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

