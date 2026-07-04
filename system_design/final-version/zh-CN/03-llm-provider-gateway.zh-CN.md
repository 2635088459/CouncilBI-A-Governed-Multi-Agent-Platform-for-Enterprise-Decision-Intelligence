# 03 大模型 Provider Gateway

## 1. 为什么不能到处直接调大模型 API

真实项目里，大模型不是简单写几行 SDK 调用就结束。我们要关心：

1. 哪个模型更适合分类、生成 SQL、总结答案？
2. 超时怎么办？
3. 调用失败怎么办？
4. token 花了多少？
5. 成本是多少？
6. prompt 版本怎么管理？
7. 以后换 Provider 怎么办？

所以要做一个 LLM Provider Gateway。它就像“模型调用总插座”，业务模块只插到这个插座上，不直接绑死某一家模型厂商。

## 2. 核心职责

LLM Gateway 负责：

1. 统一请求格式。
2. 统一响应格式。
3. 模型路由。
4. prompt 模板管理。
5. 超时、重试、熔断。
6. token 和成本统计。
7. 调用日志和 trace。
8. 安全过滤和敏感信息处理。

## 3. 请求模型

建议内部统一成：

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

这样 SQL Agent、RAG Agent、Verifier Agent 都可以用同一套接口。

## 4. 响应模型

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

大白话：不只要答案，还要知道这次模型调用“用了谁、花了多少、慢不慢、有没有风险”。

## 5. 模型路由策略

不同任务可以走不同模型：

1. 意图识别：便宜快速模型。
2. SQL 生成：更稳定、指令遵循强的模型。
3. 答案合成：接收受限 SQL rows 和 evidence snippets 的 grounded 模型调用，只能基于这些上下文回答。
4. 评估 judge：独立模型或规则混合，避免自评自夸。

路由可以从配置里读，例如：

```text
task_type=sql_generation -> provider=openai, model=gpt-4.1-mini
task_type=answer_summary -> provider=openai, model=gpt-4.1
task_type=eval_judge -> provider=openai, model=gpt-4.1
```

具体模型名后续以实际 API 和预算为准，代码中不要写死。

对于 “why” 或 “explain” 这类解释问题，answer synthesis 必须使用传入的
evidence snippets，并在可用时引用 citation anchor。只要已经提供了相关
证据，就不能返回空泛的 trend summary。

## 6. 失败处理

LLM 调用失败时不要直接让整个系统崩掉。

推荐策略：

1. 单次请求设置 timeout。
2. 网络错误做有限重试。
3. 连续失败触发 circuit breaker。
4. SQL 生成失败时返回安全错误，不执行任何 SQL。
5. 总结失败时可以返回结构化数据和简短 fallback 说明。
6. 记录失败事件到 observability。

## 7. 成本控制

必须记录：

1. 每次调用 token。
2. 每个用户 token。
3. 每个组织 token。
4. 每个任务类型成本。
5. 每天、每月预算。

当接近预算时：

1. 降级到便宜模型。
2. 限制长上下文。
3. 对普通用户限流。
4. 管理员收到告警。

## 8. 和评估系统的关系

Spec 10 里的 eval runner 和 release gate 可以使用 LLM Gateway：

1. 评估集统一调用当前候选模型。
2. 记录每个 eval case 的 token 和成本。
3. 质量下降时阻止发布。
4. 新 prompt 版本必须跑评估才能上线。

## 9. 实施顺序

1. 定义 `LLMClient` 抽象接口。
2. 实现一个真实 Provider adapter。
3. 实现一个 fake/mock adapter 供测试使用。
4. 把 Orchestrator 中需要模型的地方改为依赖 LLM Gateway。
5. 加入 token/cost logging。
6. 给 SQL/RAG/summary 路径加失败降级测试。
7. 增加 grounded answer-synthesis 测试，证明 SQL rows 和 RAG evidence 会通过
   Gateway 传入，并被最终答案实际使用。
