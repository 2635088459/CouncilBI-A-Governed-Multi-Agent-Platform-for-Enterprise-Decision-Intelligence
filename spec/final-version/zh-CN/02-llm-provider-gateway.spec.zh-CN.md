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
| FR-FV02-009 | Orchestrator 集成必须接受注入的 `LLMClient`，不得直接依赖 provider SDK。 |
| FR-FV02-010 | 当配置了 `LLMClient` 时，最终 answer synthesis 必须把用户问题、safe SQL、有上限的表格 rows、有上限的 evidence snippets 传给 LLM gateway 后再生成自然语言答案。 |
| FR-FV02-011 | 当没有配置 LLM client 或 provider 失败时，answer synthesis 必须有 deterministic grounded fallback。 |
| FR-FV02-012 | 不支持或不属于业务域的用户文本不得落入默认 demo SQL generation 或 answer synthesis。 |
| FR-FV02-013 | Mock 和 fallback answer synthesis 必须尊重用户问题，不得仅因为 rows 中存在某个值就推断用户没有问的指标。 |
| FR-FV02-014 | Answer synthesis 必须基于实际返回 table schema 做领域化表达，support-ticket evidence 不能覆盖 revenue rows，revenue evidence 也不能覆盖 support-ticket rows。 |
| FR-FV02-015 | Docker runtime 配置必须把 LLM provider 变量，包括可选 OpenAI-compatible provider 设置，传给 backend 和 worker，且不能硬编码 secret。 |

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

### 5.3 Observability Event Metadata
每个完成态 LLM trace event 必须包含：
- `provider`
- `model`
- `latency_ms`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `estimated_cost`
- `finish_reason`
- `attempts`

Provider failure event 必须只包含脱敏后的 `error` 值，不得暴露 API key、原始 provider payload 或底层 SDK 异常细节。

### 5.4 Runtime 配置
真实 provider adapter 必须从环境变量或 secret manager 读取密钥。当前 OpenAI-compatible adapter 使用：
- `CHATBI_LLM_PROVIDER`：选择 `mock` 或 `openai`，默认是 `mock`。
- `CHATBI_LLM_MODEL`：选择路由模型；未配置时，`mock` 默认 `mock-chatbi-small`，`openai` 默认 `gpt-4o-mini`。
- `CHATBI_LLM_TIMEOUT_MS`：配置 task timeout，默认是 `1000`。
- `CHATBI_LLM_MAX_RETRIES`：配置有上限的 retry，默认是 `1`。
- `CHATBI_LLM_BACKOFF_MS`：配置 retry backoff，默认是 `25`。
- `OPENAI_API_KEY`：provider secret。
- `OPENAI_BASE_URL`：可选 endpoint override。
- `OPENAI_MODEL`：可选 smoke test model override。

缺少必要 provider secret 时，必须在初始化阶段失败，并且不得发起网络请求。

## 6. 验收标准
| ID | 标准 |
|---|---|
| AC-FV02-001 | 现有 agent workflow 可以使用 mock provider 离线运行。 |
| AC-FV02-002 | 配置真实 API key 后，可以运行真实 provider smoke test。 |
| AC-FV02-003 | 每次 LLM call 都能在 observability 中看到 token 和 latency。 |
| AC-FV02-004 | timeout 或 provider failure 返回安全降级响应。 |
| AC-FV02-005 | SQL generation provider failure 不会进入 SQL execution。 |
| AC-FV02-006 | Cost record 可以按 user、organization、task type 和 day 聚合。 |
| AC-FV02-007 | support-ticket 业务问题可以由 SQL rows 和 document evidence 进入 `answer_synthesis` LLM task 后生成答案。 |
| AC-FV02-008 | `hello` 这类 prompt 会返回 unsupported-question response，不执行 SQL、不返回 revenue rows、不运行 answer synthesis。 |
| AC-FV02-009 | 混合 revenue/support prompt 如果返回的是 revenue rows，不得生成 support-ticket 文案或 support-ticket evidence。 |
| AC-FV02-010 | 本地 Docker 默认保持 mock；设置 `CHATBI_LLM_PROVIDER=openai` 和 `OPENAI_API_KEY` 后可以切换到 OpenAI-compatible provider。 |

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
| TC-FV02-008 | unit | Cost store 按 user、organization、task type 和 day 聚合 token 与 estimated cost。 |
| TC-FV02-009 | unit | Runtime config 默认构建 mock gateway，并拒绝不支持的 provider。 |
| TC-FV02-010 | integration | Orchestrator 会把 safe SQL、返回 rows 和 evidence citation 发送给 `answer_synthesis`。 |
| TC-FV02-011 | unit | Runtime config 会把 `sql_generation` 和 `answer_synthesis` 都路由到配置的 provider。 |
| TC-FV02-012 | integration negative | Unsupported text 在 SQL generation 和 answer synthesis 前被拒绝。 |
| TC-FV02-013 | unit | Mock answer synthesis 只有在用户问题要求该 metric 时才回答 highest-revenue。 |
| TC-FV02-014 | integration | 混合 revenue/support prompt 在返回 revenue rows 时不会附加 support-ticket answer text 或 evidence。 |
| TC-FV02-015 | config | Docker Compose 将 LLM provider 和 OpenAI-compatible 环境变量传给 backend 与 worker。 |

已实现测试覆盖：
- `tests/test_llm_provider_gateway.py`
- `tests/test_simple_orchestrator.py`

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
| FR-FV02-009 | AC-FV02-001, AC-FV02-005 | TC-FV02-004, TC-FV02-005 |
| FR-FV02-010 | AC-FV02-007 | TC-FV02-010 |
| FR-FV02-011 | AC-FV02-004, AC-FV02-007 | TC-FV02-010, TC-FV02-011 |
| FR-FV02-012 | AC-FV02-008 | TC-FV02-012 |
| FR-FV02-013 | AC-FV02-008 | TC-FV02-013 |
| FR-FV02-014 | AC-FV02-009 | TC-FV02-014 |
| FR-FV02-015 | AC-FV02-010 | TC-FV02-015 |
| NFR-FV02-003 | AC-FV02-006 | TC-FV02-008 |
| NFR-FV02-002 | AC-FV02-004 | TC-FV02-002, TC-FV02-009 |
