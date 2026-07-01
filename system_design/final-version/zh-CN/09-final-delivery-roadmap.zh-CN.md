# 09 最终交付路线图

## 1. 总路线

现在项目已经有核心 ChatBI 骨架。下一阶段不要同时开很多战线，而是按工业项目依赖关系推进。

推荐顺序：

1. Auth/RBAC/Tenant。
2. LLM Gateway。
3. Embedding + Vector RAG。
4. 数据 seed 和 migration。
5. Admin observability。
6. Resilience。
7. Cloud/Kubernetes。
8. Final demo 和 release package。

## 2. Phase 1：用户体系和权限

目标：

1. 用户能注册登录。
2. API 能识别 user/org/role。
3. Admin-only 接口不能被普通用户访问。
4. 查询历史和 trace 按租户隔离。

验收标准：

1. 普通用户访问 admin endpoint 返回 403。
2. A 组织用户不能看到 B 组织数据。
3. 所有 chat query 都有 user/org trace。

## 3. Phase 2：LLM Gateway

目标：

1. 接入真实大模型 API。
2. 保留 mock provider 供测试。
3. 统一 token/cost/latency 记录。
4. 支持 timeout/retry。

验收标准：

1. 本地可用 mock 跑测试。
2. 配置 API key 后可调真实模型。
3. 每次模型调用能在 observability 中看到 token 和耗时。

## 4. Phase 3：Embedding + Vector RAG

目标：

1. 文档可切片。
2. chunk 可 embedding。
3. 向量可存储和检索。
4. RAG 回答有 citation。
5. 检索必须带租户过滤。

验收标准：

1. 上传或 seed 文档后可以检索。
2. A 租户不能检索 B 租户文档。
3. 无证据时系统不编造。

## 5. Phase 4：数据平台和测试数据

目标：

1. migration 管理 schema。
2. seed 生成 small/medium/large 数据。
3. 业务数据和文档数据有关联。
4. 评估集覆盖典型问题。

验收标准：

1. 一条命令可重建本地 demo 数据。
2. CI 可跑 small seed。
3. medium seed 可支持本地集成测试。
4. large seed 可支持压测。

## 6. Phase 5：Admin Observability

目标：

1. 管理员能看 trace、eval、release gate。
2. 普通用户不能看系统内部状态。
3. 敏感日志脱敏。
4. 关键安全事件有 audit。

验收标准：

1. Admin dashboard 能展示 Spec 10 关键结果。
2. 权限测试覆盖 admin-only API。
3. release gate 失败时能阻止发布。

## 7. Phase 6：韧性和压测

目标：

1. LLM、DB、Vector search 有 timeout。
2. LLM 有 retry/backoff。
3. 外部依赖有 circuit breaker。
4. API 有 rate limit。
5. 长任务进入 queue。

验收标准：

1. mock LLM 超时时系统能降级。
2. 高并发下不会无限占用资源。
3. 压测报告记录 P50/P95/P99 延迟。

## 8. Phase 7：云端和 Kubernetes

目标：

1. Docker image 可构建。
2. Kubernetes manifests 可部署。
3. 云端 PostgreSQL/Redis/Secret 可配置。
4. staging 环境可访问。
5. CI/CD 可跑测试和部署。

验收标准：

1. staging URL 可打开。
2. 健康检查通过。
3. HPA 和 resource limit 配置存在。
4. 关键 secret 不进入 git。

## 9. Phase 8：最终提交包

最终交付应包含：

1. 主 README 英文版和中文版。
2. final-version 系统设计文档。
3. API 文档。
4. 本地启动说明。
5. 云端部署说明。
6. 测试和评估报告。
7. Demo 脚本。
8. 架构图。
9. 风险和后续计划。

## 10. 下一步推荐

最推荐下一步直接做 Phase 1：Auth/RBAC/Tenant。

原因很简单：它是后面所有工业级能力的地基。没有它，LLM、RAG、Admin、Observability、云端部署都会缺少“谁可以看什么”的基本答案。
