# Spec FV-06：韧性与压测

来源设计：
- [韧性与规模设计](../../../system_design/final-version/zh-CN/07-resilience-and-scale.zh-CN.md)
- [最终交付路线图](../../../system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md)

## 1. 目的
定义 timeout、retry、circuit breaker、rate limit、queue、degradation 和 load testing 等分布式系统保护能力。

## 2. 范围
范围内：
- API、agent、LLM、SQL、vector search 的 timeout budget。
- 外部依赖 transient failure 的 retry/backoff。
- circuit breaker、rate limit、bulkhead、queue、load-test report。

范围外：
- 多地域 active-active 高可用。
- 完整 chaos engineering 平台。

## 3. 功能需求
| ID | 需求 |
|---|---|
| FR-FV06-001 | 外部依赖调用必须有可配置 timeout。 |
| FR-FV06-002 | LLM 和 vector call 必须对 transient failure 支持 bounded retry/backoff。 |
| FR-FV06-003 | 外部依赖连续失败必须打开 circuit breaker。 |
| FR-FV06-004 | API request 必须按 user 和 organization 限流。 |
| FR-FV06-005 | 长任务必须通过 async queue 执行并暴露 task status。 |
| FR-FV06-006 | 离线 evaluation/indexing 不能耗尽在线 chat 资源。 |
| FR-FV06-007 | RAG、charting、summarization、forecasting 失败时必须有安全降级。 |
| FR-FV06-008 | load-test report 必须包含 P50、P95、P99、error rate、test configuration。 |

## 4. 非功能需求
| ID | 需求 |
|---|---|
| NFR-FV06-001 | timeout failure 应返回受控错误，不能返回 stack trace。 |
| NFR-FV06-002 | 多副本部署下 rate-limit counter 应使用 Redis 或共享存储。 |
| NFR-FV06-003 | 默认 mock LLM load test 不得调用真实 provider，避免成本失控。 |
| NFR-FV06-004 | 10k tasks 下 queue status endpoint 本地 P95 应 <= 250ms。 |

## 5. 验收标准
| ID | 标准 |
|---|---|
| AC-FV06-001 | mock LLM timeout 触发降级响应，不导致 chat API 崩溃。 |
| AC-FV06-002 | provider 连续失败打开 circuit breaker，并停止立即调用 provider。 |
| AC-FV06-003 | user/org rate limit 返回 429 和 retry guidance。 |
| AC-FV06-004 | 长 indexing/eval job 返回 task id 并暴露 status。 |
| AC-FV06-005 | load-test artifact 包含 P50/P95/P99 和 error rate。 |

## 6. 测试计划
| ID | 层级 | 描述 |
|---|---|---|
| TC-FV06-001 | unit | timeout wrapper 返回受控 timeout error。 |
| TC-FV06-002 | unit | retry policy 重试 transient failure，但不重试 non-retryable error。 |
| TC-FV06-003 | unit | circuit breaker 达阈值打开，cooldown 后 half-open。 |
| TC-FV06-004 | integration | rate limit 达阈值后返回 429。 |
| TC-FV06-005 | integration | 长 RAG indexing job 返回 task id 和状态流转。 |
| TC-FV06-006 | integration negative | RAG、charting、summarization、forecasting failure 降级回答，不让整个 query 失败。 |
| TC-FV06-007 | load | mock LLM/API load test 生成 latency 和 error-rate report。 |

已实现测试覆盖：
- `tests/test_resilience.py`
- `tests/test_llm_provider_gateway.py`
- `tests/test_embedding_vector_rag.py`
- `tests/test_load_testing.py`
- `tests/test_app.py`
- `tests/test_http_app.py`
- `tests/test_worker_handoff.py`
- `tests/test_plan_executor.py`
- `tests/test_summarization.py`

已实现源码模块：
- `src/chatbi/resilience.py`
- `src/chatbi/rate_limit.py`
- `src/chatbi/llm/gateway.py`
- `src/chatbi/embedding_vector_rag.py`
- `src/chatbi/load_testing.py`
- `src/chatbi/application/app.py`
- `src/chatbi/orchestration/worker.py`
- `src/chatbi/orchestration/executor.py`
- `src/chatbi/summarization.py`

已实现 NFR 证据：
- `NFR-FV06-002`：`ChatBIApplication` 支持注入 user 和 organization 的 `RateLimitCounterStore`。默认本地实现为 `InMemorySlidingWindowRateLimitStore`；多副本部署可以在同一接口后接入 Redis/shared implementation。`tests/test_app.py::test_handle_chat_query_supports_shared_rate_limit_store_across_replicas` 验证跨 app replica 的共享 counter 行为。

## 7. 追踪矩阵
| 需求 | 验收标准 | 测试 |
|---|---|---|
| FR-FV06-001 | AC-FV06-001 | TC-FV06-001 |
| FR-FV06-002 | AC-FV06-001 | TC-FV06-002 |
| FR-FV06-003 | AC-FV06-002 | TC-FV06-003 |
| FR-FV06-004 | AC-FV06-003 | TC-FV06-004 |
| FR-FV06-005 | AC-FV06-004 | TC-FV06-005 |
| FR-FV06-006 | AC-FV06-004 | TC-FV06-005 |
| FR-FV06-007 | AC-FV06-001 | TC-FV06-006 |
| FR-FV06-008 | AC-FV06-005 | TC-FV06-007 |
