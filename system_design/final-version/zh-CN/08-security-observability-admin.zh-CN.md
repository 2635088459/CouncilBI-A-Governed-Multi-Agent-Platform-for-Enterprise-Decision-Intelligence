# 08 安全、可观测性与 Admin 控制台

## 1. 为什么 Spec 10 不能直接给所有用户看

Spec 10 做了评估、trace、metrics、release gate、runtime logs。这些内容非常有价值，但也非常敏感。

它们可能包含：

1. 用户问题。
2. SQL。
3. 错误堆栈。
4. 模型调用信息。
5. 数据表名和字段名。
6. 安全策略命中记录。

所以这些内容必须放进 Admin 权限边界里。

## 2. Admin Console 应该看什么

管理员面板建议包含：

1. 系统健康：API 延迟、错误率、队列长度。
2. LLM 健康：调用次数、失败率、token、成本。
3. SQL 安全：拦截次数、危险模式、慢查询。
4. RAG 健康：检索命中率、embedding 任务状态。
5. Evaluation：评估集结果、失败案例、趋势。
6. Release Gate：是否允许发布。
7. Audit：用户行为、安全事件、权限变更。

## 3. 可观测三件套

### 3.1 Logs

结构化日志应该包含：

1. `timestamp`
2. `level`
3. `trace_id`
4. `user_id`
5. `org_id`
6. `event_type`
7. `message`
8. `metadata`

敏感内容要脱敏。

### 3.2 Metrics

核心指标：

1. request latency。
2. request error rate。
3. LLM latency。
4. LLM token usage。
5. SQL guardrail block count。
6. RAG hit rate。
7. eval pass rate。
8. release gate status。

### 3.3 Traces

每个 chat query 应有完整 trace：

1. API received。
2. auth checked。
3. orchestrator planned。
4. SQL generated。
5. guardrail checked。
6. DB executed。
7. RAG searched。
8. answer summarized。
9. response returned。

## 4. 安全审计

必须审计：

1. 登录成功/失败。
2. 权限变更。
3. Admin 访问 trace/eval/audit。
4. SQL 被拦截。
5. 敏感字段访问。
6. 模型 Provider 配置变更。
7. release gate 覆盖或强制发布。

## 5. PII 和敏感信息保护

需要处理：

1. 日志里不要存明文密码/token。
2. 用户问题如果包含敏感信息，写日志前做 masking。
3. SQL 结果中的敏感字段按权限脱敏。
4. LLM prompt 中避免放入不必要的个人信息。
5. 导出报告要带权限检查。

## 6. 和 Spec 10 的关系

Spec 10 已经是这部分的基础：

1. evaluation repository。
2. runtime metrics。
3. trace events。
4. release gate。
5. evaluation report。
6. quality dashboard。

最终版本要做的是：

1. 给这些 API 加 admin 权限。
2. 给这些数据加 `org_id`。
3. 把结果展示到 Admin Console。
4. 接入 OpenTelemetry/Prometheus/Grafana 或等价方案。

## 7. 实施顺序

1. 标记所有 observability/eval/release gate API 为 admin-only。
2. 给日志和 trace 加 user/org 上下文。
3. 给敏感字段加 masking。
4. 增加 admin audit event。
5. 建 Admin Console 页面。
6. 接入 metrics dashboard。
7. 写权限测试和安全测试。
