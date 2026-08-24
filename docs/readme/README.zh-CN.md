# Governed Multi-Agent ChatBI Platform

**InsightOps AI** —— 一个受治理的多智能体 ChatBI 平台。业务用户用自然语言提问，系统返回一个基于 SQL 结果、RAG 证据引用、guardrail 校验过的答案，并附带完整的可审计链路。

English version: [README.en.md](README.en.md)

---

## 目录

1. [目标用户是谁](#1-目标用户是谁)
2. [要解决的问题与产品定位](#2-要解决的问题与产品定位)
3. [技术栈](#3-技术栈)
4. [系统架构](#4-系统架构)
5. [多智能体编排](#5-多智能体编排)
6. [语义层与受治理的-nl2sql](#6-语义层与受治理的-nl2sql)
7. [SQL-Guardrail、治理与数据安全](#7-sql-guardrail治理与数据安全)
8. [RAG 设计：混合检索](#8-rag-设计混合检索)
9. [模型选择：LLM 与 Embedding](#9-模型选择llm-与-embedding)
10. [认证、RBAC 与租户隔离](#10-认证rbac-与租户隔离)
11. [可观测性、审计与维护](#11-可观测性审计与维护)
12. [测试、评测与-Release-Gate](#12-测试评测与-release-gate)
13. [部署](#13-部署)
14. [API 一览](#14-api-一览)
15. [仓库结构](#15-仓库结构)
16. [本地开发](#16-本地开发)
17. [工程决策记录](#17-工程决策记录)
18. [当前状态与路线图](#18-当前状态与路线图)
19. [文档索引](#19-文档索引)

---

## 1. 目标用户是谁

“受治理”这个词只有在不同角色能看到不同东西时才有意义，因此项目围绕四类用户来设计：

| 角色 | 需求 | 得到什么 |
|---|---|---|
| **业务用户** | 不写 SQL 就能问“为什么收入下降了” | 自然语言对话、带证据引用的答案、图表；看不到其他用户的提问和 admin 数据 |
| **分析师** | 减少重复报表工作，信任数字来源 | 团队共享历史、语义指标目录、有证据支撑的答案、可运行已批准的评测集 |
| **数据/平台团队** | Guardrail、可审计性、可运维 | SQL guardrail 审计记录、PII 脱敏、只读数据库角色、按租户的数据隔离、release gate |
| **管理员（Admin）** | 系统健康、安全、质量控制 | Admin 控制台（`/api/v2/admin/...`）、trace、评测、release gate 状态、角色变更审计日志，均需 `admin:*` 权限 |
| **工程评审者** | 判断这是不是一个真实系统，而不是薄薄一层 LLM wrapper | 195 个测试文件、严格模式 `pyright`、带边界测试的分层架构，以及一份记录“发现问题并修复”而非只写“计划要做”的 follow-up 审计文档 |

## 2. 要解决的问题与产品定位

大多数企业 BI 系统要么是静态 dashboard，要么依赖分析师按需手写 SQL。业务用户经常被卡在反复追问数据团队：

- 为什么上个月收入下降了？
- 哪个业务线或用户群体导致了异常？
- 下个季度收入趋势会怎样？
- 这个答案是不是真的基于我们的指标定义和业务证据，还是模型在“编”？

InsightOps AI 把一个自然语言问题路由给多个专职智能体协作完成：语义理解、SQL 生成与校验、只读执行、图表生成、异常检测/预测、RAG 证据检索、答案验证——每一步都被追踪、审计，并受评测/release 流程把关。目标不是一个聊天机器人 demo，而是一个把安全、治理、可观测性当作一等系统属性，而非事后补丁的决策智能平台。

## 3. 技术栈

| 层 | 选型 | 为什么 |
|---|---|---|
| 后端语言 | Python 3.11+ | 强类型约束（`src` 和 `tests` 均以 `pyright` 严格模式检查），且在 analytics/RAG 路径上生态丰富 |
| API 框架 | FastAPI（`src/chatbi/api/http.py`） | 原生异步、带类型的请求/响应模型，适合一个编排多智能体的后端 |
| 主数据库 | PostgreSQL 16（`docker-compose.yml`、`docker/postgres/init`） | 承载 auth、query history、guardrail 审计、RAG chunk/embedding、可观测性和评测数据；同时托管只读业务 schema |
| 向量检索 | 同一个 PostgreSQL 实例上的 pgvector | 不需要额外运维一套向量基础设施；`knowledge.doc_embeddings` 在 SQL 层面完成 owner/role 范围过滤（见第 8 节） |
| 缓存/任务信号 | Redis 7 | API 与 analytics/RAG worker 之间的会话与异步任务交接 |
| 关键词检索 | BM25（`rank-bm25`） | 混合 RAG 路径中真正的词法打分，而非用 token 重叠率做近似 |
| 重排（Rerank） | Cross-encoder（`sentence-transformers`，可选 `rerank` extra） | 对候选结果做二次打分；模型未安装时会明确回退到 rerank 之前的排序 |
| LLM 接入 | Provider 抽象网关（`src/chatbi/llm/`），mock + OpenAI provider | 详见第 9 节 |
| Embedding | Provider 抽象客户端，mock + OpenAI `text-embedding-3-small` | 详见第 9 节 |
| 前端 | React + Vite + TypeScript（`frontend/`） | 聊天界面、admin 控制台、任务状态页；构建为静态资源由 nginx 提供（`Dockerfile.frontend`） |
| 容器化 | Docker Compose（frontend、backend、worker、PostgreSQL、Redis） | 一条命令即可拉起与生产拓扑一致的本地环境 |
| 编排 | Kubernetes 清单脚手架（`k8s/chatbi-runtime.yaml`） | 在完整云部署 profile 之前先验证运行时架构 |
| CI | GitHub Actions（`.github/workflows/spec-10-release-gate.yml`） | 每次 push 都跑一遍 release-gate 测试/类型检查组合 |
| 测试 | `pytest`（195 个测试文件）、`pyright`（严格模式） | 详见第 12 节 |

## 4. 系统架构

```text
Frontend / Chat UI（React + Vite）
  -> Backend API（FastAPI）
    -> Auth / RBAC / 租户上下文层
    -> Application facade（src/chatbi/application/app.py）
      -> Agent Orchestrator
        -> Semantic / NL2SQL Agent
        -> SQL Guardrail
        -> 只读查询执行器
        -> Analytics Agent（预测、异常检测）
        -> RAG Agent（混合检索）
        -> Verifier Agent
        -> Visualization Agent
      -> Query History
      -> Guardrail / Query Audit
      -> Trace Events
      -> Evaluation Runner
      -> Golden Dataset Mining
      -> Quality Dashboard

数据面：
  PostgreSQL（应用数据、auth、审计、RAG chunk、评测、可观测性）
  pgvector（文档 embedding，按 owner/role 范围隔离）
  Redis（会话与异步任务交接）
  对象存储 / 本地磁盘（用户上传文件）

运维面：
  /healthz、/readyz、/metrics
  按 trace_id 查询的 trace detail
  脱敏后的结构化 JSON 日志
  admin 可观测性汇总
  release gate 和评测报告
```

### 核心运行流程——一次受治理的 ChatBI 查询

```text
用户提问
  -> auth 校验 + 组织/租户解析
  -> 问题分类（TaskType：sql_query | chart | analytics | rag_explanation | verification | file_data）
  -> 基于指标/表目录的语义解析
  -> SQL 候选生成
  -> SQL guardrail allow/deny 决策（并写审计记录）
  -> 在受限数据库角色下只读执行
  -> 按需做图表/分析增强
  -> 按需做 RAG 证据检索
  -> 答案合成，且只能基于返回的行数据和证据
  -> 答案验证
  -> 带 trace_id 的响应包
```

## 5. 多智能体编排

系统不会把整个问题丢给一次模型调用了事。`QuestionClassifier`（`src/chatbi/orchestration/routing.py`）先给问题打上一个 `TaskType`（`sql_query`、`chart`、`analytics`、`rag_explanation`、`verification`、`file_data`），`ExecutionPlanBuilder` 再把它转成一个 `ExecutionPlan`：一组有序的 `AgentPlanStep`，每一步声明所用 agent、所处执行阶段（`sql` → `fanout` → `verify`）及其依赖关系。`PlanExecutor`（`src/chatbi/orchestration/executor.py`）负责实际执行这个计划，`SimpleOrchestrator`（`src/chatbi/orchestration/simple_orchestrator.py`）把整套流程和 history、guardrail、trace 记录接在一起。

各 Agent（`src/chatbi/agents/`）职责单一：

| Agent | 职责 |
|---|---|
| `SqlAgentRunner` | 通过语义层解析问题，并经 LLM 网关的 `sql_generation` 路由生成 SQL 候选 |
| Guardrail（治理层，虽不叫“agent”，但每次都在链路中） | 在任何 SQL 候选触达数据库之前完成校验、改写和 allow/deny 把关 |
| 只读查询执行器 | 在只读 Postgres 角色下执行 guardrail 已批准的 SQL，返回 `TableResult` |
| `AnalyticsAgentRunner` / `AnalyticsServiceRunner` | 对查询结果做预测和异常检测 |
| `VisualizationAgentRunner` | 在问题是图表型问题时生成 `ChartSpec` 供前端渲染 |
| `RagAgentRunner` | 执行混合检索（见第 8 节），为“为什么/解释类”问题提供证据 |
| `FederatedQueryAgent` | 把只读查询能力扩展到 admin 批准的业务数据源 |
| `FileDataAgent` / `FileScopedRetriever` | 回答限定在用户上传文件范围内的问题，遵守文件所有权/分享规则 |
| `VerifierAgentRunner` / `AnswerAssemblyVerifier` | 在答案返回前，对照来源核对已组装好的答案 |

为什么这样设计，而不是一个大 prompt：

- **Guardrail 挡在模型和数据库之间。** SQL 生成是一次模型调用；SQL *执行* 不是——它只在一次独立的、非 LLM 的 guardrail 决策之后才会发生（见第 7 节）。哪怕出现 prompt 注入或模型幻觉出 `DROP TABLE`，也无法触达数据库，因为模型根本没有执行权限。
- **每个 agent 都能独立测试。** `tests/test_sql_agent.py`、`tests/test_rag_agent.py`、`tests/test_analytics_agent.py`、`tests/test_verifier_agent.py` 等分别测试单个 adapter 的契约，而不必每次都跑一遍完整端到端链路。
- **置信度是聚合出来的，不是模型自称的。** `ConfidenceAggregator`（`src/chatbi/orchestration/confidence.py`）把实际运行过的 agent 的信号（SQL 是否成功、RAG 命中质量、verifier 结论）按来源加权聚合成一个分数，而不是直接相信某个模型自己报的置信度。
- **异步任务被交接出去，而不是同步阻塞。** 耗时的 analytics/RAG 任务通过 `WorkerHandoffQueue`（`src/chatbi/orchestration/worker.py`）交给独立的 worker 进程（`Dockerfile.worker`），一个慢预测不会拖住聊天请求本身。
- **每一步都会被 trace。** `AgentStepTracer` 独立于最终 HTTP 响应记录每个 agent 步骤的耗时、状态和错误，因此某一个 agent 出错不会抹掉对其他步骤的可见性。

## 6. 语义层与受治理的 NL2SQL

`src/chatbi/semantic/` 位于原始问题和 SQL 生成之间：

- `catalog.py` / `catalog_store.py` —— 模型被允许引用的指标和表目录，让“收入”解析到一个统一约定的定义，而不是模型看列名随便猜的结果。
- `question_parser.py` —— 在生成 SQL 之前先抽取结构化意图（指标、维度、时间窗口、过滤条件）。
- `sql_generator.py` —— 基于解析出的问题和目录构建 SQL 候选，走 LLM 网关的 `sql_generation` 任务类型。
- `schema_drift.py` —— 检测线上数据库 schema 是否已经偏离目录描述，让过期的指标定义被标记出来，而不是悄悄给出错误答案。

NL2SQL 这一步从不直接和数据库对话——它唯一的输出是一个必须通过下面 guardrail 校验的 SQL *候选*。

## 7. SQL Guardrail、治理与数据安全

`src/chatbi/governance/` 让“只读”成为一个系统级属性，而不是一句 prompt 指令：

- **`SqlStatementValidator`**（`sql_validator.py`）解析候选 SQL，拒绝一切不是简单、安全 `SELECT` 的语句——不允许 DDL、DML，也不允许多语句拼接。
- **`SqlObjectAccessPolicy`**（`policies.py`）配合 **`business_table_catalog.py`** 强制执行表和列的白名单。
- **`RowLimitRewriter`**（`sql_rewriter.py`）注入行数上限，确保任何查询都不会返回无界数据。
- **`QueryTimeoutPolicy`**（`timeout_policy.py`）限制执行时间。
- **`PiiResultMasker`**（`masking.py`、`masking_plan.py`）在执行之后，根据调用者权限对结果中的敏感字段做脱敏。
- **`GuardrailAuditLog`**（`audit.py`、`audit_recorder.py`、`query_audit.py`）记录每一次 allow/deny 决策、SQL 哈希和原因，可通过 `GET /api/v2/admin/query-audit/{audit_trace_id}`（仅 admin）查询。
- **`ReadOnlyQueryExecutor`**（`readonly_executor.py`、`readonly_probe.py`）只针对 `CHATBI_READONLY_DATABASE_URL` 执行——一个独立的、数据库级别的只读 Postgres 角色（`docker/postgres/init`），也就是说 guardrail 之外还有数据库自身这一道防线，而不只是应用层逻辑。

纵深防御的具体含义是：即使 SQL guardrail 出现 bug，它所执行的数据库连接本身也没有写权限；即使某条写操作侥幸漏过，能触碰到的对象范围仍然受 object-access policy 限制；每一次决策——无论放行还是拒绝——都被写入与该请求 `trace_id` 关联的审计日志。

## 8. RAG 设计：混合检索

RAG 系统负责用真实业务文档（指标定义、政策、经营复盘）回答“为什么/解释类”问题，而不是让模型自己猜；它被实现为一个诚实的混合检索管线，而不是一个“只有向量搜索”的捷径。

### 为什么是混合检索，而不是纯向量

纯语义搜索会漏掉关键词搜索能捕捉到的精确词（产品编码、工单 ID、精确指标名），纯关键词搜索又会漏掉 embedding 能捕捉到的同义改写。检索管线把两者融合后再做重排：

```text
文档 -> 解析 -> 分块 -> Embedding -> pgvector（按 owner/role 范围隔离）

问题 -> Embedding -> 向量相似度检索              \
     -> BM25 关键词打分（rank-bm25）              > 混合融合 -> Top-2K
     -> 租户 / owner / 权限过滤                  /
                                                        |
                                          cross-encoder 重排（可选）
                                                        |
                                        带引用来源的上下文构建器
                                                        |
                                                LLM 生成答案 + 引用
```

- **Embedding**：`EmbeddingClient` 协议（`src/chatbi/embedding_vector_rag.py`），测试用 `MockEmbeddingClient`，生产部署用 `OpenAIEmbeddingClient`（`embedding_vector_config.py`）。
- **关键词打分**：在已经过权限过滤的候选集合上做真正的 BM25，而不是用 Jaccard/token 重叠率替代。
- **向量存储**：本地/开发环境用 `InMemoryVectorStore`，生产环境用基于 pgvector 的 `PostgresKnowledgeVectorSource`（表为 `knowledge.doc_embeddings`），由 `CHATBI_PGVECTOR_SEARCH_ENABLED` 开关控制。候选行的 `owner_user_id` / `allowed_roles` 范围过滤**直接写在 SQL 里**，而不是取回结果后在应用代码里再过滤一遍——从而在查询层面就堵住了同一类租户数据泄露风险。
- **重排（Rerank）**：可选的 cross-encoder 二次打分（`sentence-transformers`，`rerank` extra）对 Top-2K 候选再评一次分，由 `CHATBI_RERANKER_ENABLED` 开关控制，模型不可用时会明确回退到 rerank 之前的排序——reranker 是质量增强项，不是硬依赖。
- **输出结构**：每个 RAG 答案都携带 `citations`、`evidence_chunks`、一个 `confidence` 分数，以及在确实没检索到相关内容时的显式 `missing_evidence_warning`——系统被设计成“找不到证据就明说”，而不是编一个答案出来。

### 不仅评测最终答案，也评测检索本身

`golden_dataset/cases.json` 是一份真实的、贴合 schema 的、经过自我验证的业务问题集合，带有 `expected_chunk_ids`——这是“检索是否找对了 chunk”的 ground truth，而不只是“最终答案听起来是否合理”。`retrieval_evaluation.py` 用 **Hit Rate@K** 和 **MRR** 对它打分，目前作为纯可观测性指标追踪（暂不设 release-gate 阈值，这是刻意为之——要等真正的生产基线出来之后再定阈值才有意义）。

### 这套设计是怎么走到今天的——一段诚实的审计记录

这套检索管线的设计经过了一次代码级审计后被重写。审计发现：文档中描述的四阶段架构（embedding → 分块 → 混合打分 → rerank）形状上确实已经存在，但四个阶段里有三个其实是占位实现——一条代码路径上用哈希分桶伪 embedding 代替真实向量，用 token 重叠率代替 BM25，“rerank”阶段实际上只是对前一步已经算好的分数重新排了个序，而没有真的跑第二次模型打分。每一个问题都被单独写成一份 follow-up 设计文档并逐一修复（`system_design/final-version/zh-CN/04-followups/01`–`05`），随后又一轮复查发现 reload 路径其实没有真正用上已回填的 pgvector 向量，而 golden dataset 本身也需要换成真实内容，而非合成 fixture（`04-followups/06`）。这段历史被完整保留在仓库里，而不是被概括抹去——因为一个愿意记录自己“发现问题并修复问题”过程的系统，比一个只写“计划要做什么”的系统更可信。

### 持续改进：Golden Dataset Mining

`golden_dataset_mining.py` 会从可观测性 log/trace 存储中挖掘生产环境中真实被问过的问题，把它们变成 golden dataset 的候选用例。这些存储默认是内存态的；`CHATBI_OBSERVABILITY_POSTGRES_ENABLED` 会把它们切换成持久化的 Postgres 实现，让挖掘工作可以针对一个真实部署的完整问题历史运行，而不仅仅是当前进程的运行时长——把检索评测变成一个能从真实使用中持续改进的闭环，而不是一次性的固定 fixture。

## 9. 模型选择：LLM 与 Embedding

### 为什么要有一个网关，而不是直接调 SDK

`src/chatbi/llm/gateway.py` 是所有模型调用的唯一入口。它让系统有一个统一的地方去实施超时、带退避的重试、按任务类型的模型路由，以及 token/成本追踪——也让切换 provider 时不需要改动 agent 代码，因为每个 provider 都实现同一个 `LLMProvider` 协议（`complete(request, route) -> LLMResponse`）。

### 为什么默认是 mock-first

`.env.example` 中默认是 `CHATBI_LLM_PROVIDER=mock` 和 `CHATBI_EMBEDDING_PROVIDER=mock`。`MockLLMProvider` 是确定性的、完全不依赖网络的：相同输入产生相同输出，不需要 API key，没有调用成本，也不会因为线上模型的抖动而变得不稳定。这是一个刻意的设计选择，不是偷懒留下的占位符——正因如此，195 个测试文件和 CI release gate 才能在不产生任何调用费用、也不依赖外部 API 可用性的前提下稳定运行。Agent 契约、guardrail 行为、编排逻辑都是针对这个确定性实现来验证的；到了真实部署，只需要在边缘替换 provider 即可。

### 为什么第一个真实 provider 选 OpenAI

`OpenAIChatProvider` 是一个刻意做得很轻量的、基于标准库 HTTP 的 adapter（不依赖任何 SDK），这样就不会给基线测试路径引入沉重的依赖。默认路由的模型是 `gpt-4o-mini`（`llm/config.py` 的 `_llm_model_from_env`）——之所以选它作为默认值，是因为一次聊天分析类问题往往会触发多次模型调用（意图分类、SQL 生成、答案合成），而不是一次，`gpt-4o-mini` 在成本和延迟之间取得了适合这种场景的平衡；`CHATBI_LLM_MODEL` 可以按部署环境覆盖。同样的理由也适用于默认 embedding 模型 `text-embedding-3-small`：1536 维、单 token 成本低，对于以“召回率优先于最高精度”为目标的 chunk 级语义检索来说已经足够。

### 按任务类型路由，而不是一个模型打天下

网关按 `task_type`（`intent_classification`、`sql_generation`、`answer_synthesis`、`evidence_reasoning`）路由，因此一个部署环境可以通过配置——而不是改代码——把更便宜更快的模型分给意图分类，把指令遵循能力更强的模型分给 SQL 生成，两者互不影响。答案合成被显式地“接地”：它只能接收上游实际返回的、经过边界限制的 SQL 行数据和证据片段；对于“为什么/解释类”问题，它必须引用证据的出处锚点，而不能退化成一个泛泛的趋势总结——这一点由 `tests/test_answer_synthesis.py` 强制保证。

### 扩展到其他 provider

因为 `LLMProvider` 和 `EmbeddingClient` 都是协议（protocol），接入 Anthropic、Gemini 或本地模型服务只是新增一个 adapter，而不需要重写 orchestrator 或 agent 代码——`providers.py` 目前提供 `MockLLMProvider` 和 `OpenAIChatProvider`，这就是未来扩展的落点。

## 10. 认证、RBAC 与租户隔离

`src/chatbi/auth.py` 实现的是真实的认证系统，而不是一个占位 stub：

- **数据模型**：`auth.organizations`、`auth.users`（哈希密码、roles、permissions、用于吊销的 `token_version`）、`auth.refresh_sessions`（哈希后的 refresh token、过期时间、吊销状态）、`auth.role_audit_events`（每一次角色/权限变更，含变更前后、操作者、目标用户）。
- **Token**：短期 access token（默认 15 分钟）加较长期的 refresh session（默认 14 天），通过 `POST /api/v2/auth/signup`、`signin`、`refresh` 签发，通过 `POST /api/v2/auth/sessions/revoke` 吊销。
- **RBAC**：admin-only 接口检查的是具体的权限字符串（`admin:eval:read`、`admin:eval:write`、`admin:trace:read`、`admin:audit:read`、`admin:release_gate:read`、`admin:user:write` 等），而不是一个粗粒度的 `is_admin` 标记，这样一个组织可以只授予可观测性的读权限，而不必连带授予用户角色的写权限。
- **租户隔离**：`org_id` 限定了 query history、RAG 文档/embedding、评测结果、审计日志和 trace 的可见范围。RAG 的 owner/role 范围过滤（见第 8 节）是在 SQL 层面强制执行的，而不是检索后再在应用层过滤——设计上明确把“堵住这一类泄露”作为一条命名的验收标准（一条测试用例：租户/owner A 不能检索到租户/owner B 的 chunk）。
- **文件**：上传的文件带有明确的所有权和分享模型（`src/chatbi/files/sharing.py`、`POST /api/v2/files/{file_id}/share`）——只有文件所有者，或同一组织内的 admin，才能删除文件或管理其分享设置。

## 11. 可观测性、审计与维护

- **Trace**：每一次聊天查询都可以通过 `trace_id` 端到端追踪——API 接收、auth 校验、orchestrator 规划、SQL 生成、guardrail 校验、数据库执行、RAG 检索、答案合成、响应返回（`GET /api/v2/governance/traces/{trace_id}`，仅 admin）。
- **结构化日志**：JSON 日志携带 `timestamp`、`level`、`trace_id`、`user_id`、`org_id`、`event_type`、`message`、`metadata`，敏感内容在写入前就已脱敏。
- **指标**：请求延迟/错误率、LLM 延迟/token 用量、guardrail 拦截次数、RAG 命中率、评测通过率、release gate 状态，均暴露在 `/metrics`，并在 `GET /api/v2/admin/observability/summary` 为运维人员做汇总。
- **持久化存储，按需开启**：可观测性日志和 trace 默认是内存态的（本地开发快速、零配置），设置 `CHATBI_OBSERVABILITY_POSTGRES_ENABLED=true` 后会切换到一个池化、持久化的 PostgreSQL 存储，可配置保留窗口（`CHATBI_OBSERVABILITY_RETENTION_DAYS`，默认 30 天），并有定时清理任务清除过期记录——这正是第 8 节中 golden dataset mining 能够针对真实部署历史（而不只是当前进程运行时长）运行的前提。
- **维护闭环**：持久化可观测性 + golden dataset mining + Hit Rate/MRR 检索评测三者组合，构成了平台内置的“从真实使用中持续改进 RAG 质量”的反馈闭环，而不是依赖人工抽查。
- **迁移**：`migrations.py` / `migrate.py` 为 PostgreSQL 实例的 schema 演进提供了 CLI 工具。

## 12. 测试、评测与 Release Gate

- **单元与集成测试**：`tests/` 下共 195 个测试文件，覆盖 agent 契约、编排路由、guardrail 规则、auth/RBAC/租户隔离、RAG 检索与混合打分、文件上传/分享、前端状态/props 契约、Docker/Kubernetes 架构断言等等。
- **静态类型检查**：`pyright` 在 **严格模式** 下检查 `src` 和 `tests`（见 `pyproject.toml`），并配有专门的架构边界测试（`test_architecture_boundaries.py`、`test_backend_api_boundaries.py`），断言各层不会越界依赖不该依赖的层。
- **评测执行器**：`EvalRunner` 执行评测用例，产出 `eval_run` / `eval_score` / `eval_failure` 记录和一份 `EvalRunReport`，通过 `POST /api/v2/evals/run` 和 `GET /api/v2/evals/{eval_run_id}`（仅 admin）暴露。
- **Release Gate**：`release_gate.py` 把 pytest、pyright 和评测质量检查合并成一个统一的通过/拒绝决策，通过 `GET /api/v2/release-gates/latest` 展示，并在 CI 中强制执行（`.github/workflows/spec-10-release-gate.yml`）。
- **人工验收，且必须在机器把关之后**：`human_acceptance.py` 要求有人工签字确认，但刻意被安排在 pytest/pyright/安全检查全部通过 *之后*——业务评审不能覆盖一个失败的机器把关，只能在已经通过的基础上再加一层判断。
- **检索专项评测**：针对 golden dataset 的 Hit Rate@K / MRR（见第 8 节），与答案层面的评测分开追踪。

## 13. 部署

### Docker Compose（本地）

```bash
docker compose up --build
```

| 服务 | 地址 |
|---|---|
| React 前端 | `http://localhost:8080` |
| Backend API | `http://localhost:8000` |
| PostgreSQL | `localhost:5433`（映射自容器内 `5432`） |
| Redis | `localhost:6379` |

### Kubernetes

```bash
kubectl apply -f k8s/chatbi-runtime.yaml
```

这份清单定义了 namespace、各组件的 Deployment/Service、一个 Ingress 和一个 HorizontalPodAutoscaler，其结构经过 `tests/test_k8s_runtime_architecture.py` 验证。它也已经在真实的 GKE staging 集群上跑过：`docs/deployment/cloud-kubernetes-runbook.md` 记录了构建镜像/配置 secrets/部署的完整流程，`scripts/generate_gke_staging_metrics.py`、`generate_gke_golden_correctness.py`、`generate_gke_extended_correctness.py`、`summarize_gke_concurrency.py`、`summarize_gke_repeated_concurrency.py` 可以复现负载、正确率和重复压测的稳定性基准；另外还做过一次 pod 恢复演练（删除一个正在运行的 backend pod，记录它被重新拉起并恢复健康所需的时间）。这属于 staging 级别的验证，还不是生产级 SLA——剩余的生产化加固（托管 Postgres/Redis、正式镜像仓库、给 ingress 配 TLS、为所有环境统一 secrets manager、区分 prod/staging 的环境 overlay）记录在 runbook 里；上述脚本产出的结果是本地/临时性质的（写入被 gitignore 的 `dist/report/`），不作为写死在文档里的长期结论。

## 14. API 一览

精选接口（完整契约见 `docs/api.md`）：

| Endpoint | 作用 |
|---|---|
| `GET /healthz`、`GET /readyz`、`GET /metrics` | 存活探针、就绪探针、运行时指标 |
| `POST /api/v2/auth/signup` / `signin` / `refresh` / `sessions/revoke` | 认证生命周期 |
| `POST /api/v2/chat/query` | 主 ChatBI 查询入口（带认证上下文） |
| `GET /api/v2/chat/history` | 当前用户自己的查询历史 |
| `GET /api/v2/query/{trace_id}`、`GET /api/v2/requests/{trace_id}` | 查询回放/详情 |
| `POST /api/v2/analytics/analyze`、`POST /api/v2/analytics/tasks` | 分析/预测 |
| `POST /api/v2/documents/index` | RAG 文档索引 |
| `POST /api/v2/files/upload`、`.../share` | 文件上传与分享 |
| `PUT /api/v2/admin/users/{user_id}/roles` | Admin：修改用户角色（会被审计） |
| `GET /api/v2/admin/audits/roles` | Admin：角色变更审计日志 |
| `GET /api/v2/admin/query-audit/{audit_trace_id}` | Admin：SQL guardrail 决策详情 |
| `GET /api/v2/governance/traces/{trace_id}` | Admin：完整 trace 详情 |
| `POST /api/v2/evals/run`、`GET /api/v2/evals/{eval_run_id}` | Admin：运行/查看评测 |
| `GET /api/v2/release-gates/latest` | Admin：release gate 状态 |
| `GET /api/v2/admin/observability/summary` | Admin：运维汇总面板 |

## 15. 仓库结构

| 路径 | 作用 |
|---|---|
| `src/chatbi/api/` | FastAPI adapter 和 API payload 模型 |
| `src/chatbi/application/` | 连接 API 和领域 workflow 的 application facade |
| `src/chatbi/orchestration/` | Agent 路由、执行计划、trace、状态 |
| `src/chatbi/agents/` | SQL、RAG、analytics、visualization、verifier、file、federated-query agent |
| `src/chatbi/semantic/` | 语义目录、问题解析、NL2SQL 辅助逻辑 |
| `src/chatbi/governance/` | SQL guardrail、policy、审计、脱敏、只读执行 |
| `src/chatbi/llm/` | LLM provider 网关、路由、类型、provider 实现 |
| `src/chatbi/rag*.py`、`embedding_vector_rag.py` | RAG 契约、索引、hydration、混合检索、worker |
| `src/chatbi/golden_dataset*.py` | Golden dataset 用例与 mining 管线 |
| `src/chatbi/auth.py` | 认证、RBAC、租户上下文 |
| `src/chatbi/analytics*.py` | Analytics、预测、持久化、异步 worker |
| `src/chatbi/observability*.py` | Span、日志、持久化 Postgres 存储、数据保留策略 |
| `src/chatbi/evaluation*.py` | 评测打分、持久化、报告、benchmark |
| `src/chatbi/files/` | 上传、分片上传、存储、分享、留存策略 |
| `src/chatbi/frontend/` | 前端状态、props、fixture、静态构建 |
| `frontend/` | React + Vite 聊天界面与 admin 控制台 |
| `spec/`、`system_design/` | 版本化规格与系统设计文档（v1、v2、final-version，中英双语） |
| `verification/` | 各 spec 的验证报告 |
| `k8s/`、`docker-compose.yml`、`Dockerfile.*` | 部署脚手架 |
| `.github/workflows/` | CI release gate |

## 16. 本地开发

```bash
# Python 环境
python -m venv .venv313
.venv313/bin/python -m pip install --upgrade pip
.venv313/bin/python -m pip install -e ".[dev]"

# 运行 focused tests
.venv313/bin/python -m pytest tests/test_app.py tests/test_http_app.py

# 运行完整测试套件
.venv313/bin/python -m pytest

# 严格静态检查
.venv313/bin/python -m pyright src tests

# 启动本地环境
docker compose up --build
```

## 17. 工程决策记录

- SQL 执行始终只读，且必须先通过 guardrail 校验才能触达数据库；只读角色又在数据库层面被再次强制执行。
- `trace_id` 是贯穿 backend、orchestrator、审计、评测和日志的一等标识符。
- 核心 agent workflow 都配有确定性测试（基于 mock LLM/embedding provider），使 release gate 保持稳定，不依赖任何线上模型。
- 新能力（reranker、pgvector 搜索、持久化可观测性）都放在显式的 opt-in 开关后面，默认关闭——启用与否是运维人员的主动决定，而不是部署时自动发生的行为变化。
- Evaluation runner、repository 和 report 读模型被拆成独立分层，让 release quality 保持可解释。
- 人工验收永远发生在机器把关之后，而不是替代机器把关。
- 设计/代码审计中发现的问题（RAG 占位实现、租户泄露风险、embedding reload bug）都被写成文档并作为命名的 follow-up spec 逐一修复，而不是悄悄打个补丁了事。

## 18. 当前状态与路线图

目前已经实现并有测试覆盖的能力：多智能体编排、语义层与 NL2SQL、SQL guardrail 与治理、真实的 auth/RBAC/租户隔离、LLM provider 网关（mock + OpenAI）、混合 RAG（真实 BM25 + embedding + 可选 cross-encoder rerank + 带 owner/role 隔离的 pgvector）、带 Hit Rate/MRR 检索评测的 golden dataset、基于真实使用数据的 golden dataset mining、可选启用的持久化可观测性存储、带人工验收环节的评测执行器与 release gate、Docker Compose 运行环境，以及一份已经在真实 GKE staging 集群上跑过负载/正确率/pod 恢复基准测试的 Kubernetes 清单（含 Ingress、HPA）。

在成为完整的生产级云服务之前，仍需推进：

| 领域 | 当前缺口 | 方向 |
|---|---|---|
| 云端部署 | 已部署到 GKE staging 集群并跑过基准测试（Ingress、HPA、secrets、负载/正确率/pod 恢复基准）；尚未达到生产级加固程度 | 托管 Postgres/Redis、正式镜像仓库、给 ingress 配 TLS、为所有环境统一 secrets manager、区分 prod/staging 的环境 overlay |
| 分布式韧性 | 已有部分超时/重试/幂等设计；尚无 circuit breaker、DLQ 或 bulkhead | Circuit breaker、退避重试、队列 DLQ、load shedding、混沌/压力测试 |
| 更多 LLM/embedding provider | 目前只有 OpenAI 是真实接入的 provider | 在现有 `LLMProvider`/`EmbeddingClient` 协议之下接入 Anthropic/Gemini adapter |
| 大规模数据 | 已有示例/演示数据；尚不足以支撑真实压测 | 合成企业级数据集生成器与 seed 管线 |
| 外部 APM | 内部 trace/日志/指标已有；尚未接外部 exporter | 接入 OpenTelemetry/Prometheus/Grafana |

## 19. 文档索引

- Final-version 规格文档：[spec/final-version/README.md](../../spec/final-version/README.md)
- Final-version 系统设计：[system_design/final-version/README.md](../../system_design/final-version/README.md)
- API 文档：[docs/api.md](../api.md)
- 本地启动指南：[docs/local-startup.md](../local-startup.md)
- 云端部署 runbook：[docs/deployment/cloud-kubernetes-runbook.md](../deployment/cloud-kubernetes-runbook.md)
- Demo 脚本：[docs/demo-script.md](../demo-script.md)
- 风险登记册：[docs/risk-register.md](../risk-register.md)
- 验证报告：[verification/](../../verification/)
