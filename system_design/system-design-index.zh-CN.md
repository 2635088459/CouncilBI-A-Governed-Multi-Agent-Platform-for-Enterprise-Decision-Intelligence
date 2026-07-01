# 系统设计总索引（中文）

English Index: [system-design-index.en.md](system-design-index.en.md)

本页是 Governed Multi-Agent ChatBI Platform 10 份系统设计文档的统一入口。每个目录保留 v1 详细设计，并新增 v2 工程化升级设计，覆盖数据库接入、Docker、本地前后端联调、Kubernetes 部署与可观测性。

最终提交版系统设计已单独整理到 [final-version/README.md](final-version/README.md)。中文版位于 [final-version/zh-CN/README.zh-CN.md](final-version/zh-CN/README.zh-CN.md)，英文版位于 [final-version/en/README.en.md](final-version/en/README.en.md)。这套文档面向工业级提交和云端上线规划，覆盖 Auth/RBAC、多租户隔离、真实 LLM API、Embedding/向量数据库、Admin 可观测性、Kubernetes、熔断限流、压测与最终交付路线图。

## 目录

- [全局架构图](#全局架构图)
- [Final Version 设计入口](#final-version-设计入口)
- [使用说明](#使用说明)
- [架构层](#架构层)
- [数据与治理层](#数据与治理层)
- [体验与智能层](#体验与智能层)
- [质量与运维层](#质量与运维层)
- [完整文档地图](#完整文档地图)
- [推荐阅读路径](#推荐阅读路径)

## 全局架构图

```mermaid
flowchart TB
	U[Business User / Analyst] --> FE[Frontend ChatBI]
	FE --> API[Backend API Gateway]

	API --> ORCH[Orchestrator / Worker]
	ORCH --> SQLA[SQL Agent]
	ORCH --> VISA[Visualization Agent]
	ORCH --> ANAA[Analytics Agent]
	ORCH --> RAGA[RAG Agent]
	ORCH --> VERA[Verifier Agent]

	SQLA --> GUARD[SQL Guardrail]
	GUARD --> DB[(PostgreSQL Business DB)]

	RAGA --> VDB[(pgvector / Vector DB)]
	RAGA --> DOC[(Business Documents)]

	API --> CACHE[(Redis Cache)]
	API --> AUDIT[(Query History / Audit)]
	ORCH --> OBS[(Tracing / Metrics / Logs)]
	API --> K8S[Kubernetes / Docker Runtime]
```

## v2 工程化升级入口

- 01 总体架构 v2：[中文](01-overall-architecture/VERSION2.zh-CN.md) / [English](01-overall-architecture/VERSION2.en.md)
- 02 多智能体编排 v2：[中文](02-agent-orchestration-design/VERSION2.zh-CN.md) / [English](02-agent-orchestration-design/VERSION2.en.md)
- 03 语义层与 NL2SQL v2：[中文](03-semantic-layer-and-nl2sql/VERSION2.zh-CN.md) / [English](03-semantic-layer-and-nl2sql/VERSION2.en.md)
- 04 SQL 安全与治理 v2：[中文](04-sql-guardrail-and-governance/VERSION2.zh-CN.md) / [English](04-sql-guardrail-and-governance/VERSION2.en.md)
- 05 数据模型 v2：[中文](05-data-model-design/VERSION2.zh-CN.md) / [English](05-data-model-design/VERSION2.en.md)
- 06 后端 API v2：[中文](06-backend-api-design/VERSION2.zh-CN.md) / [English](06-backend-api-design/VERSION2.en.md)
- 07 前端 ChatBI v2：[中文](07-frontend-chatbi-design/VERSION2.zh-CN.md) / [English](07-frontend-chatbi-design/VERSION2.en.md)
- 08 RAG 检索与证据解释 v2：[中文](08-rag-design/VERSION2.zh-CN.md) / [English](08-rag-design/VERSION2.en.md)
- 09 分析与预测 v2：[中文](09-analytics-and-forecasting-design/VERSION2.zh-CN.md) / [English](09-analytics-and-forecasting-design/VERSION2.en.md)
- 10 评估与可观测性 v2：[中文](10-evaluation-and-observability/VERSION2.zh-CN.md) / [English](10-evaluation-and-observability/VERSION2.en.md)

## Final Version 设计入口

- 语言入口：[Final Version System Design](final-version/README.md)
- 中文总目录：[Final Version 系统设计总目录](final-version/zh-CN/README.zh-CN.md)
- 英文总目录：[Final Version System Design Index](final-version/en/README.en.md)
- 00 总体提交版系统设计：[中文](final-version/zh-CN/00-executive-system-design.zh-CN.md) / [English](final-version/en/00-executive-system-design.en.md)
- 01 生产级总体架构：[中文](final-version/zh-CN/01-production-architecture.zh-CN.md) / [English](final-version/en/01-production-architecture.en.md)
- 02 登录、注册、RBAC 与租户隔离：[中文](final-version/zh-CN/02-auth-rbac-tenant-isolation.zh-CN.md) / [English](final-version/en/02-auth-rbac-tenant-isolation.en.md)
- 03 大模型 Provider Gateway：[中文](final-version/zh-CN/03-llm-provider-gateway.zh-CN.md) / [English](final-version/en/03-llm-provider-gateway.en.md)
- 04 Embedding、向量数据库与 RAG：[中文](final-version/zh-CN/04-embedding-vector-rag.zh-CN.md) / [English](final-version/en/04-embedding-vector-rag.en.md)
- 05 数据平台、迁移与大规模测试数据：[中文](final-version/zh-CN/05-data-platform-and-seed.zh-CN.md) / [English](final-version/en/05-data-platform-and-seed.en.md)
- 06 云端与 Kubernetes 部署：[中文](final-version/zh-CN/06-cloud-kubernetes-deployment.zh-CN.md) / [English](final-version/en/06-cloud-kubernetes-deployment.en.md)
- 07 熔断、限流、抗压与高可用：[中文](final-version/zh-CN/07-resilience-and-scale.zh-CN.md) / [English](final-version/en/07-resilience-and-scale.en.md)
- 08 安全、可观测性与 Admin 控制台：[中文](final-version/zh-CN/08-security-observability-admin.zh-CN.md) / [English](final-version/en/08-security-observability-admin.en.md)
- 09 最终交付路线图：[中文](final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md) / [English](final-version/en/09-final-delivery-roadmap.en.md)

## 使用说明

1. 先阅读总体架构，建立系统边界和全局认知。
2. 再阅读数据与治理，明确口径、规则与接口契约。
3. 然后阅读前端与 RAG，理解用户体验与解释机制。
4. 最后阅读分析预测与评估观测，补齐生产可用能力。

快速跳转：

- [文档 01](#文档-01总体架构)
- [文档 02](#文档-02多智能体编排)
- [文档 03](#文档-03语义层与nl2sql)
- [文档 04](#文档-04sql-安全与治理)
- [文档 05](#文档-05数据模型)
- [文档 06](#文档-06后端-api)
- [文档 07](#文档-07前端-chatbi)
- [文档 08](#文档-08rag-检索与证据解释)
- [文档 09](#文档-09分析与预测)
- [文档 10](#文档-10评估与可观测性)

## 架构层

### 文档 01：总体架构

锚点：[文档 01](#文档-01总体架构)

- 中文：[01-overall-architecture/README.zh-CN.md](01-overall-architecture/README.zh-CN.md)
- 英文：[01-overall-architecture/README.en.md](01-overall-architecture/README.en.md)

摘要：

- 系统分层与运行时拓扑
- 从提问到验证输出的端到端流程
- 跨模块通用契约与治理基线

### 文档 02：多智能体编排

锚点：[文档 02](#文档-02多智能体编排)

- 中文：[02-agent-orchestration-design/README.zh-CN.md](02-agent-orchestration-design/README.zh-CN.md)
- 英文：[02-agent-orchestration-design/README.en.md](02-agent-orchestration-design/README.en.md)

摘要：

- Orchestrator 与专用 Agent 职责边界
- 调度策略、状态机、置信度聚合
- 降级与局部失败处理机制

## 数据与治理层

### 文档 03：语义层与NL2SQL

锚点：[文档 03](#文档-03语义层与nl2sql)

- 中文：[03-semantic-layer-and-nl2sql/README.zh-CN.md](03-semantic-layer-and-nl2sql/README.zh-CN.md)
- 英文：[03-semantic-layer-and-nl2sql/README.en.md](03-semantic-layer-and-nl2sql/README.en.md)

摘要：

- 业务语义模型与指标治理
- NL 解析、SQL 规划生成、解释机制
- 版本管理与语义歧义回退

### 文档 04：SQL 安全与治理

锚点：[文档 04](#文档-04sql-安全与治理)

- 中文：[04-sql-guardrail-and-governance/README.zh-CN.md](04-sql-guardrail-and-governance/README.zh-CN.md)
- 英文：[04-sql-guardrail-and-governance/README.en.md](04-sql-guardrail-and-governance/README.en.md)

摘要：

- SQL 规则引擎与 AST 校验
- 权限控制、脱敏、限流限时限量
- 审计与回放能力

### 文档 05：数据模型

锚点：[文档 05](#文档-05数据模型)

- 中文：[05-data-model-design/README.zh-CN.md](05-data-model-design/README.zh-CN.md)
- 英文：[05-data-model-design/README.en.md](05-data-model-design/README.en.md)

摘要：

- 业务、知识、运行、治理四类数据域
- ER 结构、血缘、分区、生命周期、质量规则
- OLTP、向量库、缓存、审计存储策略

### 文档 06：后端 API

锚点：[文档 06](#文档-06后端-api)

- 中文：[06-backend-api-design/README.zh-CN.md](06-backend-api-design/README.zh-CN.md)
- 英文：[06-backend-api-design/README.en.md](06-backend-api-design/README.en.md)

摘要：

- API 分组与端点清单
- 统一请求/响应/错误模型
- 幂等、分页、限流与观测契约

## 体验与智能层

### 文档 07：前端 ChatBI

锚点：[文档 07](#文档-07前端-chatbi)

- 中文：[07-frontend-chatbi-design/README.zh-CN.md](07-frontend-chatbi-design/README.zh-CN.md)
- 英文：[07-frontend-chatbi-design/README.en.md](07-frontend-chatbi-design/README.en.md)

摘要：

- 页面架构与组件体系
- 表格/图表/证据/风险结构化渲染
- 查询中、局部失败、降级状态体验

### 文档 08：RAG 检索与证据解释

锚点：[文档 08](#文档-08rag-检索与证据解释)

- 中文：[08-rag-design/README.zh-CN.md](08-rag-design/README.zh-CN.md)
- 英文：[08-rag-design/README.en.md](08-rag-design/README.en.md)

摘要：

- 接入、切片、向量化、检索、重排
- 证据引用结构与约束
- 忠实度控制与无依据陈述抑制

## 质量与运维层

### 文档 09：分析与预测

锚点：[文档 09](#文档-09分析与预测)

- 中文：[09-analytics-and-forecasting-design/README.zh-CN.md](09-analytics-and-forecasting-design/README.zh-CN.md)
- 英文：[09-analytics-and-forecasting-design/README.en.md](09-analytics-and-forecasting-design/README.en.md)

摘要：

- 时序预处理与异常检测
- 预测策略与降级路径
- 可解释分析与不确定性表达

### 文档 10：评估与可观测性

锚点：[文档 10](#文档-10评估与可观测性)

- 中文：[10-evaluation-and-observability/README.zh-CN.md](10-evaluation-and-observability/README.zh-CN.md)
- 英文：[10-evaluation-and-observability/README.en.md](10-evaluation-and-observability/README.en.md)

摘要：

- 离线评估 + 在线 SLO 监控
- 告警、回放、发布门禁
- 持续质量改进闭环

## 完整文档地图

### 文档 01：总体架构

- 中文：[01-overall-architecture/README.zh-CN.md](01-overall-architecture/README.zh-CN.md)
- 英文：[01-overall-architecture/README.en.md](01-overall-architecture/README.en.md)

### 文档 02：多智能体编排

- 中文：[02-agent-orchestration-design/README.zh-CN.md](02-agent-orchestration-design/README.zh-CN.md)
- 英文：[02-agent-orchestration-design/README.en.md](02-agent-orchestration-design/README.en.md)

### 文档 03：语义层与NL2SQL

- 中文：[03-semantic-layer-and-nl2sql/README.zh-CN.md](03-semantic-layer-and-nl2sql/README.zh-CN.md)
- 英文：[03-semantic-layer-and-nl2sql/README.en.md](03-semantic-layer-and-nl2sql/README.en.md)

### 文档 04：SQL 安全与治理

- 中文：[04-sql-guardrail-and-governance/README.zh-CN.md](04-sql-guardrail-and-governance/README.zh-CN.md)
- 英文：[04-sql-guardrail-and-governance/README.en.md](04-sql-guardrail-and-governance/README.en.md)

### 文档 05：数据模型

- 中文：[05-data-model-design/README.zh-CN.md](05-data-model-design/README.zh-CN.md)
- 英文：[05-data-model-design/README.en.md](05-data-model-design/README.en.md)

### 文档 06：后端 API

- 中文：[06-backend-api-design/README.zh-CN.md](06-backend-api-design/README.zh-CN.md)
- 英文：[06-backend-api-design/README.en.md](06-backend-api-design/README.en.md)

### 文档 07：前端 ChatBI

- 中文：[07-frontend-chatbi-design/README.zh-CN.md](07-frontend-chatbi-design/README.zh-CN.md)
- 英文：[07-frontend-chatbi-design/README.en.md](07-frontend-chatbi-design/README.en.md)

### 文档 08：RAG 检索与证据解释

- 中文：[08-rag-design/README.zh-CN.md](08-rag-design/README.zh-CN.md)
- 英文：[08-rag-design/README.en.md](08-rag-design/README.en.md)

### 文档 09：分析与预测

- 中文：[09-analytics-and-forecasting-design/README.zh-CN.md](09-analytics-and-forecasting-design/README.zh-CN.md)
- 英文：[09-analytics-and-forecasting-design/README.en.md](09-analytics-and-forecasting-design/README.en.md)

### 文档 10：评估与可观测性

- 中文：[10-evaluation-and-observability/README.zh-CN.md](10-evaluation-and-observability/README.zh-CN.md)
- 英文：[10-evaluation-and-observability/README.en.md](10-evaluation-and-observability/README.en.md)

## 推荐阅读路径

### 路径 A：架构优先

1. [文档 01](#文档-01总体架构)
2. [文档 02](#文档-02多智能体编排)
3. [文档 06](#文档-06后端-api)
4. [文档 10](#文档-10评估与可观测性)

### 路径 B：数据安全优先

1. [文档 05](#文档-05数据模型)
2. [文档 03](#文档-03语义层与nl2sql)
3. [文档 04](#文档-04sql-安全与治理)
4. [文档 08](#文档-08rag-检索与证据解释)

### 路径 C：体验优先

1. [文档 07](#文档-07前端-chatbi)
2. [文档 06](#文档-06后端-api)
3. [文档 09](#文档-09分析与预测)
4. [文档 10](#文档-10评估与可观测性)

---

## 锚点区

### 文档 01：总体架构

### 文档 02：多智能体编排

### 文档 03：语义层与NL2SQL

### 文档 04：SQL 安全与治理

### 文档 05：数据模型

### 文档 06：后端 API

### 文档 07：前端 ChatBI

### 文档 08：RAG 检索与证据解释

### 文档 09：分析与预测

### 文档 10：评估与可观测性
