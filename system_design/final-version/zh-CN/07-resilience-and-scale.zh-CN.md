# 07 熔断、限流、抗压与高可用

## 1. 为什么需要韧性设计

工业系统一定会遇到：

1. 大模型 API 慢或失败。
2. 数据库查询很重。
3. 用户短时间内大量提问。
4. RAG indexing 长任务阻塞。
5. 某个 Agent 出错。

如果没有韧性设计，一个小故障会拖垮整个系统。

## 2. Timeout

每一层都要有超时：

1. API request timeout。
2. Agent step timeout。
3. LLM call timeout。
4. SQL execution timeout。
5. Vector search timeout。

原则：越靠近外部依赖，越不能无限等待。

## 3. Retry

适合重试的错误：

1. 网络短暂失败。
2. 429 rate limit 后的延迟重试。
3. 5xx 临时错误。

不适合重试的错误：

1. 权限不足。
2. SQL 被 Guardrail 拦截。
3. 用户输入无效。
4. 数据不存在。

重试要有 backoff，不能疯狂重复请求。

## 4. Circuit Breaker

熔断器用于保护系统。

例如 LLM Provider 连续失败：

1. 先记录失败次数。
2. 超过阈值后进入 open 状态。
3. open 状态下短时间不再调用该 Provider。
4. 过一段时间进入 half-open，试探恢复。
5. 成功后关闭熔断。

这样可以防止系统一直卡在坏掉的外部服务上。

## 5. Rate Limit

限流维度：

1. 按用户。
2. 按组织。
3. 按 IP。
4. 按 endpoint。
5. 按 LLM token budget。

普通 chat query 和 admin query 的限流策略可以不同。

## 6. Bulkhead

Bulkhead 就是隔舱设计。

例子：

1. 普通用户查询和评估任务使用不同 worker queue。
2. RAG indexing 和在线问答使用不同资源池。
3. 大模型调用和数据库查询有独立并发限制。

这样离线任务不会拖垮在线用户体验。

## 7. Async Queue

适合异步化的任务：

1. 大文件 indexing。
2. 大规模 evaluation。
3. 报告导出。
4. 长时间预测任务。
5. 大规模 seed 数据生成。

用户请求应返回 task id，然后前端轮询或订阅状态。

## 8. Load Testing

至少做三类压测：

1. API 压测：并发提问。
2. DB 压测：复杂 SQL 和大结果集。
3. LLM mock 压测：模拟模型延迟和失败。

不要直接用真实大模型做大规模压测，成本会失控。先用 mock provider。

## 9. 降级策略

系统部分失败时可以降级：

1. RAG 失败：返回结构化查询结果，并提示证据检索不可用。
2. 图表生成失败：返回表格和文本。
3. LLM 总结失败：返回 SQL 结果和基础说明。
4. 预测失败：返回历史趋势。
5. Admin dashboard 失败：不影响普通用户查询。

## 10. 实施顺序

1. 给外部依赖加 timeout。
2. 给 LLM 和 vector search 加 retry/backoff。
3. 实现 circuit breaker。
4. 加 Redis rate limit。
5. 把长任务放进 queue。
6. 写 load test 脚本。
7. 把压测结果写进 verification 文档。
