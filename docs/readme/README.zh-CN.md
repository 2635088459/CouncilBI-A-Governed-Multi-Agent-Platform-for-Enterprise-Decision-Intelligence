# Governed Multi-Agent ChatBI Platform

面向企业决策智能的自然语言 BI 平台，核心能力包括受治理的 SQL、多智能体分析、RAG 证据检索、评测体系和可观测 release gate。

> 当前状态：这是一个 production-oriented MVP，也就是“具备生产级架构意识的工程基础版本”。项目已经完成了较强的领域建模、SQL guardrail、评测、可观测性、API 契约、本地 Docker/Kubernetes 脚手架和验证报告。但它还不是完整的生产级 SaaS，因为真实 LLM Provider、登录注册/RBAC、生产级向量数据库、云端托管基础设施、大规模测试数据和分布式韧性设计仍在 final version 路线图中。

## 一句话总结

很多企业 BI 系统要么是静态 dashboard，要么依赖分析师手写 SQL。业务团队经常会问：

- 为什么上个月收入下降了？
- 哪个用户群体或产品线导致了异常？
- 下个季度收入趋势会怎样？
- 这个答案有没有基于可信指标定义和业务证据？

这个项目希望构建一个受治理的 ChatBI 平台。用户用自然语言提问，系统通过多个专职智能体协作完成：

- 语义指标识别
- SQL 生成与校验
- 只读查询执行
- 图表生成
- 异常检测和预测
- 基于 RAG 的证据检索
- 最终答案验证
- 审计、追踪、指标、评测和 release gate

这个项目的目标不是一个简单聊天机器人 demo，而是一个具备安全、治理、可观测性和可部署性的企业级决策智能系统。

## 产品定位

**InsightOps AI** 是一个面向企业业务分析场景的 governed multi-agent ChatBI 平台。

目标用户包括：

- 不会写 SQL 但需要快速业务洞察的业务用户
- 希望减少重复报表工作的数据分析师
- 需要安全、审计、权限和可观测性的 data/platform 团队
- 希望看到真实工程复杂度，而不是薄薄一层 LLM wrapper 的工程评审者

## 当前已经实现的能力

| 能力 | 状态 | 证据 |
|---|---:|---|
| v2 版本化规格文档 | 已实现 | `spec/version2/*.spec.md` |
| 系统设计文档 | 已实现 | `system_design/**/VERSION2.*.md` |
| Backend API envelope 和 routes | 已实现 | `src/chatbi/api/http.py`, `tests/test_http_app.py` |
| 多智能体编排 | 已实现 | `src/chatbi/orchestration/`, `src/chatbi/agents/` |
| Semantic layer 和 NL2SQL helper | 已实现 | `src/chatbi/semantic/`, `tests/test_semantic_*` |
| SQL guardrail 和 governance | 已实现 | `src/chatbi/governance/`, `tests/test_v2_guardrail.py` |
| 数据模型 catalog 和 migrations | 已实现 | `src/chatbi/data_model.py`, `src/chatbi/migrations.py` |
| RAG 契约和 indexing workflow 基础 | 部分完成 | `src/chatbi/rag*.py`, `tests/test_rag_*` |
| Analytics 和 forecasting | 确定性 MVP 已实现 | `src/chatbi/analytics.py`, `verification/09-analytics-and-forecasting-verification.md` |
| Evaluation 和 observability | 已实现 | `src/chatbi/evaluation_observability_v2.py`, `verification/10-evaluation-and-observability-verification.md` |
| Runtime probes 和 metrics | 已实现 | `/healthz`, `/readyz`, `/metrics` |
| 基于 trace_id 的 trace detail | 已实现 | backend 和 orchestrator `TraceEvent`、spans、audit、logs |
| Eval run 和 report API | 已实现 | `POST /api/v1/evals/run`, `GET /api/v1/evals/{eval_run_id}` |
| 本地 Docker Compose 脚手架 | 已实现 | `docker-compose.yml` |
| Kubernetes runtime 脚手架 | 已实现 | `k8s/chatbi-runtime.yaml` |
| Spec-10 release gate workflow | 已实现 | `.github/workflows/spec-10-release-gate.yml` |

## Final Version 仍需补齐的生产化缺口

这些是项目真正成为生产级云端服务前必须继续补齐的内容。

| 领域 | 当前缺口 | 目标方向 |
|---|---|---|
| LLM 集成 | 当前很多流程是 deterministic 或 adapter-based，还没有真实生产级 LLM provider gateway | 增加 OpenAI/Gemini/Anthropic adapter、prompt 模板、streaming、重试、超时预算、token 和成本追踪 |
| Embedding 和向量数据库 | RAG 有架构和本地流程，但还没有生产级 embedding/vector store 集成 | 增加 embedding provider、chunking pipeline、pgvector/Pinecone/Vertex Vector Search、top-k retrieval、context budget manager |
| 登录注册 | 还没有真实 sign up / sign in | 增加用户注册、登录、密码哈希或托管身份、JWT/session |
| RBAC 和租户隔离 | 项目已有 role 概念，但 admin-only observability 和多租户边界还不完整 | 增加 user/org/workspace model、admin-only routes、tenant filter、policy tests |
| 云端部署 | Docker/K8s 脚手架已有，但还没有 AWS/GCP 生产部署 profile | 增加 managed Postgres、Redis、对象存储、Secrets Manager、Ingress、TLS、autoscaling |
| 大规模数据 | 目前示例数据不足以支撑真实压测和分析测试 | 增加 synthetic enterprise dataset generator 和数据库 seed pipeline |
| 分布式韧性 | 已有部分 timeout/rate limit/idempotency，但还不是完整分布式韧性设计 | 增加 circuit breaker、retry/backoff、DLQ、bulkhead、load shedding、graceful degradation |
| 生产可观测性 | 内部 traces/logs/metrics 已有，但没有接外部 APM/log backend | 增加 OpenTelemetry/exporters、Prometheus/Grafana、集中式 JSON logs |
| CI/CD | Spec-10 release gate 已有，但完整平台 release pipeline 还不完整 | 增加 full test matrix、Docker build、image scan、deploy stages、migration checks |

## 架构总览

```text
Frontend / Chat UI
  -> Backend API
    -> Auth and RBAC layer
    -> Application facade
      -> Agent Orchestrator
        -> Semantic / NL2SQL Agent
        -> SQL Guardrail
        -> Read-only Query Executor
        -> Analytics Agent
        -> RAG Agent
        -> Verifier Agent
      -> Query History
      -> Audit Events
      -> Trace Events
      -> Evaluation Runner
      -> Quality Dashboard

Data plane:
  PostgreSQL
  Redis
  Vector database / pgvector
  Object storage for documents

Operations plane:
  /healthz
  /readyz
  /metrics
  trace detail by trace_id
  JSON logs
  release gate and eval reports
```

## 核心运行流程

### 1. 受治理的 ChatBI 查询

```text
用户问题
  -> semantic parsing
  -> SQL candidate generation
  -> SQL guardrail allow/deny decision
  -> read-only execution
  -> chart and analytics enrichment
  -> RAG evidence retrieval
  -> final answer verification
  -> response envelope with trace_id
```

### 2. Trace 和 Audit 检查

```text
trace_id
  -> backend TraceEvent
  -> orchestrator TraceEvent
  -> observability spans
  -> final query detail
  -> API audit
  -> SQL guardrail audit
  -> masked JSON logs
```

### 3. Evaluation 和 Release Gate

```text
eval cases
  -> EvalRunner
  -> eval_run rows
  -> eval_score rows
  -> eval_failure rows
  -> EvalRunReport
  -> quality dashboard summary
  -> release gate decision
```

## 仓库结构

| 路径 | 作用 |
|---|---|
| `src/chatbi/api/` | FastAPI adapter 和 API payload models |
| `src/chatbi/application/` | 连接 API 和领域 workflow 的 application facade |
| `src/chatbi/orchestration/` | Agent routing、execution、tracing、state |
| `src/chatbi/agents/` | SQL、RAG、analytics、visualization、verifier agent adapters |
| `src/chatbi/semantic/` | Semantic catalog、question parsing、NL2SQL helpers |
| `src/chatbi/governance/` | SQL guardrails、policy、audit、masking、read-only execution |
| `src/chatbi/rag*.py` | RAG contracts、indexing、hydration、retrieval、worker flows |
| `src/chatbi/analytics*.py` | Analytics、forecasting、persistence、async worker |
| `src/chatbi/observability*.py` | SLO、spans、logs、metrics |
| `src/chatbi/evaluation*.py` | Evaluation scoring、persistence、reports、benchmarks |
| `src/chatbi/frontend/` | Frontend state、props、fixtures、static demo assets |
| `spec/version2/` | v2 machine-readable specs |
| `system_design/` | 英文和中文系统设计文档 |
| `verification/` | 每个 spec 的验证报告 |
| `k8s/` | Kubernetes deployment scaffold |
| `.github/workflows/` | CI release gate workflow |

## API 入口

已实现的主要 API：

| Endpoint | 作用 |
|---|---|
| `GET /healthz` | Liveness probe |
| `GET /readyz` | Readiness probe |
| `GET /metrics` | Runtime metrics text |
| `POST /api/v1/chat/query` | 主 ChatBI 查询入口 |
| `GET /api/v1/query/{trace_id}` | Query replay/detail |
| `GET /api/v1/observability/traces/{trace_id}` | Trace、audit、logs、final answer inspection |
| `GET /api/v1/quality/dashboard` | SLO、alert、release gate dashboard payload |
| `POST /api/v1/evals/run` | 运行 evaluation suite |
| `GET /api/v1/evals/{eval_run_id}` | 查询保存后的 evaluation report |
| `POST /api/v1/sql/guardrail/check` | SQL guardrail check |

## 本地开发

### Python 环境

```bash
python -m venv .venv313
.venv313/bin/python -m pip install --upgrade pip
.venv313/bin/python -m pip install -e ".[dev]"
```

### 运行 focused tests

```bash
.venv313/bin/python -m pytest tests/test_app.py tests/test_http_app.py
```

### 运行 spec-10 focused verification

```bash
.venv313/bin/python -m pytest \
  tests/test_trace_events.py \
  tests/test_runtime_metrics.py \
  tests/test_runtime_probes.py \
  tests/test_observability_logs.py \
  tests/test_evaluation_repository.py \
  tests/test_evaluation_cases.py \
  tests/test_evaluation_report.py \
  tests/test_release_gate.py \
  tests/test_release_gate_ci.py \
  tests/test_spec10_release_gate_workflow.py \
  tests/test_human_acceptance.py \
  tests/test_trace_benchmark.py \
  tests/test_evaluation_benchmark.py \
  tests/test_simple_orchestrator.py \
  tests/test_app.py
```

### 运行 focused static checks

```bash
.venv313/bin/python -m pyright \
  src/chatbi/trace_events.py \
  src/chatbi/runtime_metrics.py \
  src/chatbi/observability_logs.py \
  src/chatbi/evaluation_repository.py \
  src/chatbi/evaluation_cases.py \
  src/chatbi/evaluation_report.py \
  src/chatbi/release_gate.py \
  src/chatbi/release_gate_ci.py \
  src/chatbi/human_acceptance.py \
  src/chatbi/trace_benchmark.py \
  src/chatbi/evaluation_benchmark.py \
  src/chatbi/evaluation_observability_v2.py
```

### 运行 Docker Compose

```bash
docker compose up --build
```

本地服务：

- frontend placeholder: `http://localhost:8080`
- backend API: `http://localhost:8000`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

### Kubernetes 脚手架

```bash
kubectl apply -f k8s/chatbi-runtime.yaml
```

当前 Kubernetes 文件是 runtime architecture validation scaffold。生产化前还需要加入云托管数据库、真实镜像、TLS ingress、secret management、resource requests/limits、HPA 和环境 overlay。

## Verification Reports

| Spec | Verification |
|---|---|
| 01 Overall Architecture | `verification/01-overall-architecture-verification.md` |
| 02 Agent Orchestration | `verification/02-agent-orchestration-verification.md` |
| 03 Semantic Layer and NL2SQL | `verification/03-semantic-layer-and-nl2sql-verification.md` |
| 04 SQL Guardrail and Governance | `verification/04-sql-guardrail-and-governance-verification.md` |
| 05 Data Model | `verification/05-data-model-verification.md` |
| 06 Backend API | `verification/06-backend-api-verification.md` |
| 07 Frontend ChatBI | `verification/07-frontend-chatbi-verification.md` |
| 08 RAG | `verification/08-rag-verification.md` |
| 09 Analytics and Forecasting | `verification/09-analytics-and-forecasting-verification.md` |
| 10 Evaluation and Observability | `verification/10-evaluation-and-observability-verification.md` |

## 系统设计文档

主要入口：

- `system_design/system-design-index.en.md`
- `system_design/system-design-index.zh-CN.md`
- `system_design/system-design-parts-list.md`

关键 v2 设计领域：

- Overall Architecture
- Agent Orchestration
- Semantic Layer and NL2SQL
- SQL Guardrail and Governance
- Data Model
- Backend API
- Frontend ChatBI
- RAG Retrieval and Evidence
- Analytics and Forecasting
- Evaluation and Observability

## Final Version Roadmap

推荐生产化顺序：

1. **Authentication and RBAC**
   - sign up、sign in、JWT/session
   - user、organization、workspace、role、admin policy
   - admin-only observability/evaluation/audit APIs

2. **LLM Provider Gateway**
   - OpenAI/Gemini/Anthropic adapter
   - prompt 模板和版本管理
   - retries、timeout budgets、fallback、token 和 cost tracking
   - model call tracing 和 evaluation hooks

3. **Embedding and Vector Search**
   - embedding provider abstraction
   - 带 overlap 和 metadata 的 document chunking
   - pgvector 或外部 vector DB
   - 带 tenant 和 permission filter 的 top-k retrieval
   - 用于 token reduction 的 context budget manager

4. **Production Data and Persistence**
   - durable eval、trace、audit、history、RAG stores
   - migration pipeline
   - large synthetic enterprise dataset generator
   - performance fixtures

5. **Distributed Resilience**
   - circuit breaker
   - retry with exponential backoff
   - deadline propagation
   - queue DLQ
   - bulkheads and load shedding
   - chaos and load tests

6. **Cloud Deployment**
   - AWS 或 GCP reference architecture
   - managed Postgres、Redis、object storage、secrets manager
   - Kubernetes overlays
   - TLS ingress、HPA、resource limits
   - deployment runbook and rollback plan

7. **Production Observability**
   - OpenTelemetry traces
   - Prometheus/Grafana
   - centralized JSON logs
   - alert routing
   - incident response playbook

## Decision Log

重要工程选择：

- SQL execution 必须 read-only，并且在访问数据库前通过 guardrail。
- `trace_id` 是贯穿 backend、orchestrator、audit、eval、logs 的一等请求标识。
- 核心 agent workflow 使用 deterministic tests，保证 release gate 稳定。
- 早期使用 in-memory repositories，但接口形状向 PostgreSQL-backed stores 对齐。
- Evaluation runner、repository、report read model 分层，方便解释 release quality。
- Human acceptance 必须在 machine gates 之后，不能覆盖 pyright、pytest 或 safety check 失败。

## 当前 Readiness Assessment

| 维度 | 当前成熟度 |
|---|---|
| 架构清晰度 | 强 |
| 领域建模 | 强 |
| Guardrails and governance | 强 MVP |
| Evaluation and observability | 强 MVP |
| Frontend demo path | 部分完成 |
| Auth and RBAC | 未达到生产级 |
| Real LLM integration | 未达到生产级 |
| Vector DB and embeddings | 未达到生产级 |
| Cloud deployment | 只有脚手架 |
| Production resilience | 部分完成 |
| Large-scale data validation | 部分完成 |

## 推荐下一步

创建最终生产 readiness plan：

```text
verification/final-version-readiness.md
```

这份文档应该把上面的 roadmap 拆成 epics、blockers、优先级、验收标准和实施顺序。

之后第一个真正实现的 production epic 建议是 **Auth and RBAC**，因为生产级 observability、admin dashboard、tenant isolation 和 data permission 都依赖真实用户身份。
