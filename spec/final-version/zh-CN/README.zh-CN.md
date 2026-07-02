# Final Version Specs — 中文

来源路线图：[最终交付路线图](../../../system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md)

这套 spec 用来指导最终工业级提交。每份文档都按 SDD + TDD 写：先把设计边界和需求讲清楚，再把验收标准和测试用例写清楚。实现前必须保证每条功能需求都能追踪到验收标准和测试。

## Spec 清单

| # | Spec | Phase | 状态 |
|---|---|---|---|
| 01 | [Auth、RBAC 与多租户隔离](01-auth-rbac-tenant-isolation.spec.zh-CN.md) | 用户体系和权限 | Verified/Implemented |
| 02 | [LLM Provider Gateway](02-llm-provider-gateway.spec.zh-CN.md) | 真实大模型接入 | Draft |
| 03 | [Embedding 与 Vector RAG](03-embedding-vector-rag.spec.zh-CN.md) | 真实 RAG 检索 | Draft |
| 04 | [数据平台与 Seed 数据](04-data-platform-and-seed.spec.zh-CN.md) | 数据和测试语料 | Draft |
| 05 | [Admin 可观测性](05-admin-observability.spec.zh-CN.md) | 管理员专属 Spec 10 能力 | Draft |
| 06 | [韧性与压测](06-resilience-and-load-testing.spec.zh-CN.md) | 分布式系统准备度 | Draft |
| 07 | [云端与 Kubernetes 部署](07-cloud-kubernetes-deployment.spec.zh-CN.md) | 云端上线 | Draft |
| 08 | [最终提交包](08-final-submission-package.spec.zh-CN.md) | 最终交付 | Draft |

## SDD + TDD 规则

1. 需求必须编号，必须可测试。
2. admin、trace、eval、audit、release gate 数据必须有权限测试，不能裸露给普通用户。
3. 真实 LLM 和 embedding provider 必须有 mock/fake provider，保证测试稳定。
4. 多租户隔离必须覆盖 chat history、trace、document、embedding、audit。
5. 云端和 Kubernetes spec 必须包含健康检查、secret、资源限制和 smoke test。
6. 最终发布必须包含 pyright、pytest、安全检查、评估门禁和人工 demo 验收。
