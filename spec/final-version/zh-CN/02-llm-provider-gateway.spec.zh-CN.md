# Spec FV-02：LLM Provider Gateway

来源设计：
- [LLM Provider Gateway 设计](../../../system_design/final-version/zh-CN/03-llm-provider-gateway.zh-CN.md)
- [最终交付路线图](../../../system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md)

## 1. 目的
定义一个可控、可观测、可测试的大模型调用层，用于 intent classification、SQL generation、answer summary、evidence reasoning 和 evaluation。

## 2. 范围
范围内：
- `LLMClient` 接口、provider adapter、mock provider、模型路由、prompt version。
- timeout、retry/backoff、token/cost/latency 记录、trace event。
- SQL 生成、RAG 总结、eval judge 的安全失败处理。

范围外：
- 训练或 fine-tuning 自定义模型。
- 把 provider API key 提交到仓库。

## 3. 功能需求
| ID | 需求 |
|---|---|
| FR-FV02-001 | 系统必须定义 provider-neutral 的 `LLMClient` 接口。 |
| FR-FV02-002 | 系统必须包含 deterministic mock provider 用于测试。 |
| FR-FV02-003 | 真实 provider 必须通过环境变量或 secret manager 配置。 |
| FR-FV02-004 | LLM request 必须包含 task type、prompt version、user/org context、trace id。 |
| FR-FV02-005 | LLM response 必须记录 model、provider、latency、token、cost estimate、finish reason。 |
| FR-FV02-006 | SQL generation 失败时绝不能执行 SQL。 |
| FR-FV02-007 | Provider call 必须支持 timeout 和有上限的 retry/backoff。 |
| FR-FV02-008 | 所有 LLM call 必须写 observability event。 |

## 4. 非功能需求
| ID | 需求 |
|---|---|
| NFR-FV02-001 | Mock provider 测试必须稳定且不访问网络。 |
| NFR-FV02-002 | Provider timeout 必须能按 task type 配置。 |
| NFR-FV02-003 | cost tracking 必须能按 user、organization、task type、day 聚合。 |
| NFR-FV02-004 | Provider 错误返回给用户前必须脱敏。 |

## 5. 契约
### 5.1 LLMRequest
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

## 6. 验收标准
| ID | 标准 |
|---|---|
| AC-FV02-001 | 现有 agent workflow 可以使用 mock provider 离线运行。 |
| AC-FV02-002 | 配置真实 API key 后，可以运行真实 provider smoke test。 |
| AC-FV02-003 | 每次 LLM call 都能在 observability 中看到 token 和 latency。 |
| AC-FV02-004 | timeout 或 provider failure 返回安全降级响应。 |
| AC-FV02-005 | SQL generation provider failure 不会进入 SQL execution。 |

## 7. 测试计划
| ID | 层级 | 描述 |
|---|---|---|
| TC-FV02-001 | unit | Mock provider 返回 deterministic output 和 token count。 |
| TC-FV02-002 | unit | Model router 按 task type 选择配置模型。 |
| TC-FV02-003 | unit negative | 缺少 API key 时真实 provider 初始化失败。 |
| TC-FV02-004 | integration | Orchestrator 通过 `LLMClient` 调模型，而不是直接 SDK。 |
| TC-FV02-005 | integration negative | SQL generation timeout 阻止 SQL execution。 |
| TC-FV02-006 | observability | LLM call 写入 provider、model、latency、tokens。 |
| TC-FV02-007 | optional smoke | 只有存在 provider key 时才跑真实 provider smoke test。 |

## 8. 追踪矩阵
| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV02-001 | AC-FV02-001 | TC-FV02-004 |
| FR-FV02-002 | AC-FV02-001 | TC-FV02-001 |
| FR-FV02-003 | AC-FV02-002 | TC-FV02-003, TC-FV02-007 |
| FR-FV02-004 | AC-FV02-003 | TC-FV02-006 |
| FR-FV02-005 | AC-FV02-003 | TC-FV02-006 |
| FR-FV02-006 | AC-FV02-005 | TC-FV02-005 |
| FR-FV02-007 | AC-FV02-004 | TC-FV02-005 |
| FR-FV02-008 | AC-FV02-003 | TC-FV02-006 |

