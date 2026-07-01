# Governed Multi-Agent ChatBI Platform

Enterprise decision intelligence platform for natural-language BI, governed SQL, multi-agent analytics, RAG evidence retrieval, and release-gated observability.

> Current status: production-oriented MVP with verified architecture slices. The system has strong domain modeling, guardrails, evaluation, observability, API contracts, local Docker/Kubernetes scaffolding, and verification coverage. It is not yet a fully production-ready SaaS deployment because real LLM provider integration, authentication/RBAC, production vector search, cloud-managed infrastructure, large-scale seed data, and resilience hardening are still planned final-version work.

## Executive Summary

Most enterprise BI systems are either static dashboards or analyst-driven SQL workflows. Business users still wait on data teams for follow-up questions such as:

- Why did revenue drop last month?
- Which segment caused the anomaly?
- Can we forecast next quarter's revenue?
- Is this answer grounded in trusted business definitions and evidence?

This project builds a governed ChatBI platform where a user can ask a business question in natural language and the system coordinates specialized agents for:

- semantic metric interpretation
- SQL generation and validation
- read-only query execution
- chart generation
- anomaly detection and forecasting
- RAG-based evidence retrieval
- answer verification
- audit, trace, metrics, evaluation, and release-gate enforcement

The design goal is not a simple demo chatbot. The target is an enterprise-grade decision intelligence platform with security, governance, observability, and deployability treated as first-class system concerns.

## Product Positioning

**InsightOps AI** is a governed multi-agent ChatBI platform for enterprise business analytics.

It is designed for:

- business users who need fast answers without writing SQL
- analysts who want to reduce repetitive reporting work
- data and platform teams who need guardrails, auditability, and operational control
- engineering reviewers who want to see a realistic full-stack AI system rather than a thin LLM wrapper

## What Is Implemented Today

| Capability | Status | Evidence |
|---|---:|---|
| Versioned system specs | Implemented | `spec/version2/*.spec.md` |
| System design docs | Implemented | `system_design/**/VERSION2.*.md` |
| Backend API envelope and routes | Implemented | `src/chatbi/api/http.py`, `tests/test_http_app.py` |
| Multi-agent orchestration | Implemented | `src/chatbi/orchestration/`, `src/chatbi/agents/` |
| Semantic layer and NL2SQL helpers | Implemented | `src/chatbi/semantic/`, `tests/test_semantic_*` |
| SQL guardrail and governance | Implemented | `src/chatbi/governance/`, `tests/test_v2_guardrail.py` |
| Data model catalog and migrations | Implemented | `src/chatbi/data_model.py`, `src/chatbi/migrations.py` |
| RAG contracts and indexing workflow | Partial | `src/chatbi/rag*.py`, `tests/test_rag_*` |
| Analytics and forecasting | Implemented deterministic MVP | `src/chatbi/analytics.py`, `verification/09-analytics-and-forecasting-verification.md` |
| Evaluation and observability | Implemented | `src/chatbi/evaluation_observability_v2.py`, `verification/10-evaluation-and-observability-verification.md` |
| Runtime probes and metrics | Implemented | `/healthz`, `/readyz`, `/metrics` |
| Trace detail by trace id | Implemented | backend and orchestrator `TraceEvent`, spans, audit, logs |
| Eval run and report API | Implemented | `POST /api/v1/evals/run`, `GET /api/v1/evals/{eval_run_id}` |
| Local Docker Compose scaffold | Implemented | `docker-compose.yml` |
| Kubernetes scaffold | Implemented | `k8s/chatbi-runtime.yaml` |
| Spec-10 release gate workflow | Implemented | `.github/workflows/spec-10-release-gate.yml` |

## Final Version Gaps

These are known gaps before positioning the project as a production cloud service.

| Area | Gap | Target Direction |
|---|---|---|
| LLM integration | Current flows are mostly deterministic or adapter-based; no production LLM provider gateway yet | Add OpenAI/Gemini/Anthropic provider abstraction, prompt templates, streaming, retries, timeout budgets, cost tracking |
| Embeddings and vector DB | RAG has architecture and local flows, but no production embedding/vector store integration | Add embedding provider, chunking pipeline, pgvector/Pinecone/Vertex Vector Search, top-k retrieval, context budget manager |
| Authentication | No real sign up/sign in flow | Add user registration, login, password hashing or managed identity, JWT/session handling |
| RBAC and tenant isolation | Some role concepts exist, but observability/admin APIs are not fully locked down | Add user/org/workspace model, admin-only routes, per-tenant filters, policy tests |
| Cloud deployment | Docker/K8s scaffolds exist, but no AWS/GCP production deployment profile | Add managed Postgres, Redis, object storage, secrets manager, ingress, TLS, autoscaling |
| Large-scale data | Sample data exists but not enough for realistic load and analytics testing | Add synthetic data generator and database seed pipeline |
| Resilience | Some timeout/rate-limit/idempotency pieces exist, but not full distributed resilience | Add circuit breaker, retry/backoff, queue DLQ, bulkheads, load shedding, graceful degradation |
| Production observability | Internal traces/logs/metrics exist, but no external APM/log backend | Add OpenTelemetry/exporters, Prometheus/Grafana, centralized JSON logs |
| CI/CD | Spec-10 release gate exists, but full platform release pipeline is not complete | Add full test matrix, Docker build, image scan, deploy stages, migration checks |

## Architecture

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

## Core Runtime Flows

### 1. Governed ChatBI Query

```text
User question
  -> semantic parsing
  -> SQL candidate generation
  -> SQL guardrail allow/deny decision
  -> read-only execution
  -> chart and analytics enrichment
  -> RAG evidence retrieval
  -> final answer verification
  -> response envelope with trace_id
```

### 2. Trace and Audit Inspection

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

### 3. Evaluation and Release Gate

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

## Repository Map

| Path | Purpose |
|---|---|
| `src/chatbi/api/` | FastAPI adapter and API payload models |
| `src/chatbi/application/` | Application facade that coordinates domain workflows |
| `src/chatbi/orchestration/` | Agent routing, execution, tracing, state |
| `src/chatbi/agents/` | SQL, RAG, analytics, visualization, verifier agent adapters |
| `src/chatbi/semantic/` | Semantic catalog, question parsing, NL2SQL helpers |
| `src/chatbi/governance/` | SQL guardrails, policies, audit, masking, read-only execution |
| `src/chatbi/rag*.py` | RAG contracts, indexing, hydration, retrieval, worker flows |
| `src/chatbi/analytics*.py` | Analytics, forecasting, persistence, async worker |
| `src/chatbi/observability*.py` | SLOs, spans, logs, metrics |
| `src/chatbi/evaluation*.py` | Evaluation scoring, persistence, reports, benchmarks |
| `src/chatbi/frontend/` | Frontend state, props, fixtures, static demo assets |
| `spec/version2/` | Machine-readable v2 specs |
| `system_design/` | English and Chinese system design documents |
| `verification/` | Verification reports by spec area |
| `k8s/` | Kubernetes deployment scaffold |
| `.github/workflows/` | CI release gate workflow |

## API Surfaces

Selected implemented API surfaces:

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Liveness probe |
| `GET /readyz` | Readiness probe |
| `GET /metrics` | Runtime metrics text |
| `POST /api/v1/chat/query` | Main ChatBI query endpoint |
| `GET /api/v1/query/{trace_id}` | Query replay/detail |
| `GET /api/v1/observability/traces/{trace_id}` | Trace, audit, logs, and final answer inspection |
| `GET /api/v1/quality/dashboard` | SLO, alert, and release gate dashboard payload |
| `POST /api/v1/evals/run` | Run evaluation suite |
| `GET /api/v1/evals/{eval_run_id}` | Read saved evaluation report |
| `POST /api/v1/sql/guardrail/check` | SQL guardrail check |

## Local Development

### Python environment

```bash
python -m venv .venv313
.venv313/bin/python -m pip install --upgrade pip
.venv313/bin/python -m pip install -e ".[dev]"
```

### Run focused tests

```bash
.venv313/bin/python -m pytest tests/test_app.py tests/test_http_app.py
```

### Run spec-10 focused verification

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

### Run focused static checks

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

### Run local Docker Compose

```bash
docker compose up --build
```

Expected local services:

- frontend placeholder: `http://localhost:8080`
- backend API: `http://localhost:8000`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

### Kubernetes scaffold

```bash
kubectl apply -f k8s/chatbi-runtime.yaml
```

The Kubernetes file is a scaffold for runtime architecture validation. It should be hardened before production with cloud-managed databases, real images, TLS ingress, secret management, resource requests/limits, HPA, and environment-specific overlays.

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

## System Design Documents

Primary index:

- `system_design/system-design-index.en.md`
- `system_design/system-design-index.zh-CN.md`
- `system_design/system-design-parts-list.md`

Key v2 design areas:

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

Recommended production hardening order:

1. **Authentication and RBAC**
   - sign up, sign in, JWT/session handling
   - user, organization, workspace, role, admin policy
   - admin-only observability/evaluation/audit APIs

2. **LLM Provider Gateway**
   - OpenAI/Gemini/Anthropic adapter
   - prompt templates and versioning
   - retries, timeout budgets, fallback, token and cost tracking
   - model call tracing and evaluation hooks

3. **Embedding and Vector Search**
   - embedding provider abstraction
   - document chunking with overlap and metadata
   - pgvector or external vector DB
   - top-k retrieval with tenant and permission filters
   - context budget manager for token reduction

4. **Production Data and Persistence**
   - durable eval, trace, audit, history, RAG stores
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
   - AWS or GCP reference architecture
   - managed Postgres, Redis, object storage, secrets manager
   - Kubernetes overlays
   - TLS ingress, HPA, resource limits
   - deployment runbook and rollback plan

7. **Production Observability**
   - OpenTelemetry traces
   - Prometheus/Grafana
   - centralized JSON logs
   - alert routing
   - incident response playbook

## Decision Log

Important engineering choices:

- Keep SQL execution read-only and guarded before database access.
- Treat trace ids as first-class request identifiers across backend, orchestrator, audit, eval, and logs.
- Keep deterministic tests for core agent workflows so release gates are stable.
- Use in-memory repositories for early correctness, but shape interfaces like future PostgreSQL-backed stores.
- Separate evaluation runner, repository, and report read model to keep release quality understandable.
- Keep human acceptance after machine gates so business review cannot override failed pyright, pytest, or safety checks.

## Current Readiness Assessment

| Dimension | Current Readiness |
|---|---|
| Architecture clarity | Strong |
| Domain modeling | Strong |
| Guardrails and governance | Strong MVP |
| Evaluation and observability | Strong MVP |
| Frontend demo path | Partial |
| Auth and RBAC | Not production-ready |
| Real LLM integration | Not production-ready |
| Vector DB and embeddings | Not production-ready |
| Cloud deployment | Scaffold only |
| Production resilience | Partial |
| Large-scale data validation | Partial |

## Recommended Next Step

Create a final production readiness plan:

```text
verification/final-version-readiness.md
```

That document should convert the roadmap above into epics, blockers, owners, acceptance criteria, implementation order, and final demo milestones.

After that, the first implementation epic should be **Auth and RBAC**, because production observability, admin dashboards, tenant isolation, and data permissions all depend on real user identity.
