# Governed Multi-Agent ChatBI Platform

**InsightOps AI** — a governed, multi-agent ChatBI platform that lets a business user ask a question in plain language and get back a SQL-grounded, RAG-cited, guardrail-checked answer with a full audit trail behind it.

中文版本：[README.zh-CN.md](README.zh-CN.md)

---

## Table of Contents

1. [Who This Is For](#1-who-this-is-for)
2. [The Problem, and the Positioning](#2-the-problem-and-the-positioning)
3. [Technology Stack](#3-technology-stack)
4. [System Architecture](#4-system-architecture)
5. [Multi-Agent Orchestration](#5-multi-agent-orchestration)
6. [Semantic Layer and Governed NL2SQL](#6-semantic-layer-and-governed-nl2sql)
7. [SQL Guardrail, Governance and Data Security](#7-sql-guardrail-governance-and-data-security)
8. [RAG Design: Hybrid Retrieval](#8-rag-design-hybrid-retrieval)
9. [Model Selection: LLM and Embeddings](#9-model-selection-llm-and-embeddings)
10. [Authentication, RBAC and Tenant Isolation](#10-authentication-rbac-and-tenant-isolation)
11. [Observability, Auditing and Maintenance](#11-observability-auditing-and-maintenance)
12. [Testing, Evaluation and Release Gates](#12-testing-evaluation-and-release-gates)
13. [Deployment](#13-deployment)
14. [API Surface](#14-api-surface)
15. [Repository Map](#15-repository-map)
16. [Local Development](#16-local-development)
17. [Engineering Decision Log](#17-engineering-decision-log)
18. [Current Status and Roadmap](#18-current-status-and-roadmap)
19. [Documentation Index](#19-documentation-index)

---

## 1. Who This Is For

The platform is built around four distinct personas, because "governed" only means something if different people are allowed to see different things:

| Persona | What they need | What they get |
|---|---|---|
| **Business user** | Ask "why did revenue drop?" without writing SQL | Natural-language chat, grounded answers with citations, charts, no access to other users' queries or admin data |
| **Analyst** | Reduce repetitive reporting, trust the numbers | Shared team history, semantic metric catalog, evidence-backed answers, ability to run approved evaluation sets |
| **Data / platform team** | Guardrails, auditability, operational control | SQL guardrail audit trail, PII masking, read-only DB role, per-tenant data isolation, release gates |
| **Admin** | System health, security, quality control | Admin console (`/api/v2/admin/...`), traces, evals, release-gate status, role-change audit log — all behind `admin:*` permissions |
| **Engineering reviewer** | Judge whether this is a real system or a thin LLM wrapper | 195 test files, strict `pyright`, layered architecture with boundary tests, a documented follow-up audit trail that shows gaps being found and closed, not just claimed |

## 2. The Problem, and the Positioning

Most enterprise BI is either a static dashboard or an analyst who writes SQL on request. Business users are stuck re-asking data teams:

- Why did revenue drop last month?
- Which segment caused the anomaly?
- Can we forecast next quarter's revenue?
- Is this answer actually grounded in our metric definitions and evidence, or is the model guessing?

InsightOps AI answers these by routing a natural-language question through specialized agents for semantic interpretation, SQL generation and validation, read-only execution, chart generation, anomaly detection/forecasting, RAG evidence retrieval, and answer verification — with every step traced, audited, and gated by an evaluation/release process. The goal is not a chatbot demo; it is a decision-intelligence platform where security, governance, and observability are first-class, not bolted on.

## 3. Technology Stack

| Layer | Choice | Why |
|---|---|---|
| Backend language | Python 3.11+ | Strong typing (`pyright` strict mode across `src` and `tests`), rich data/ML ecosystem for the analytics and RAG paths |
| API framework | FastAPI (`src/chatbi/api/http.py`) | Async-native, typed request/response models, good fit for an agent-orchestrating backend |
| Primary database | PostgreSQL 16 (`docker-compose.yml`, `docker/postgres/init`) | ACID storage for auth, history, guardrail audit, RAG chunks/embeddings, observability, and eval data; also hosts the read-only business schema |
| Vector search | pgvector on the same PostgreSQL instance | No separate vector infra to operate; `knowledge.doc_embeddings` with SQL-level owner/role scoping (see §8) |
| Cache / queue signaling | Redis 7 | Session and async task handoff between the API and the analytics/RAG workers |
| Keyword retrieval | BM25 (`rank-bm25`) | Real lexical scoring for the hybrid RAG path, not a token-overlap approximation |
| Reranking | Cross-encoder (`sentence-transformers`, optional `rerank` extra) | Second-pass re-scoring of the top candidates; falls back cleanly to the pre-rerank order when the model isn't installed |
| LLM integration | Provider-abstracted gateway (`src/chatbi/llm/`), mock + OpenAI providers | See §9 |
| Embeddings | Provider-abstracted client, mock + OpenAI `text-embedding-3-small` | See §9 |
| Frontend | React + Vite + TypeScript (`frontend/`) | Chat UI, admin console, task-status views; built to static assets served by nginx (`Dockerfile.frontend`) |
| Containers | Docker Compose (frontend, backend, worker, PostgreSQL, Redis) | One-command local environment matching the production topology |
| Orchestration | Kubernetes manifest scaffold (`k8s/chatbi-runtime.yaml`) | Runtime-architecture validation ahead of a full cloud deployment profile |
| CI | GitHub Actions (`.github/workflows/spec-10-release-gate.yml`) | Runs the release-gate test/typecheck bundle on every push |
| Testing | `pytest` (195 test files), `pyright` (strict) | See §12 |

## 4. System Architecture

```text
Frontend / Chat UI (React + Vite)
  -> Backend API (FastAPI)
    -> Auth / RBAC / tenant-context layer
    -> Application facade (src/chatbi/application/app.py)
      -> Agent Orchestrator
        -> Semantic / NL2SQL Agent
        -> SQL Guardrail
        -> Read-only Query Executor
        -> Analytics Agent (forecasting, anomaly detection)
        -> RAG Agent (hybrid retrieval)
        -> Verifier Agent
        -> Visualization Agent
      -> Query History
      -> Guardrail / Query Audit
      -> Trace Events
      -> Evaluation Runner
      -> Golden Dataset Mining
      -> Quality Dashboard

Data plane:
  PostgreSQL (app data, auth, audit, RAG chunks, eval, observability)
  pgvector (document embeddings, owner/role-scoped)
  Redis (session + async task handoff)
  Object storage / local disk (uploaded files)

Operations plane:
  /healthz, /readyz, /metrics
  trace detail by trace_id
  masked structured JSON logs
  admin observability summary
  release gate + evaluation reports
```

### Core runtime flow — a governed ChatBI query

```text
User question
  -> auth check + org/tenant resolution
  -> question classification (TaskType: sql_query | chart | analytics | rag_explanation | verification | file_data)
  -> semantic parsing against the metric/table catalog
  -> SQL candidate generation
  -> SQL guardrail allow/deny decision (+ audit record)
  -> read-only execution against a locked-down DB role
  -> chart / analytics enrichment (as needed)
  -> RAG evidence retrieval (as needed)
  -> answer synthesis, grounded only in the returned rows and evidence
  -> answer verification
  -> response envelope with trace_id
```

## 5. Multi-Agent Orchestration

The system does not hand the whole question to one model call. A `QuestionClassifier` (`src/chatbi/orchestration/routing.py`) first assigns a `TaskType` (`sql_query`, `chart`, `analytics`, `rag_explanation`, `verification`, `file_data`), and an `ExecutionPlanBuilder` turns that into an `ExecutionPlan`: an ordered set of `AgentPlanStep`s, each naming an agent, an execution stage (`sql` → `fanout` → `verify`), and its dependencies. A `PlanExecutor` (`src/chatbi/orchestration/executor.py`) then runs the plan, and a `SimpleOrchestrator` (`src/chatbi/orchestration/simple_orchestrator.py`) wires the whole thing to history, guardrail, and trace recording.

Agents (`src/chatbi/agents/`), each a narrow adapter with one job:

| Agent | Responsibility |
|---|---|
| `SqlAgentRunner` | Turns a parsed question into a SQL candidate via the semantic layer and the LLM gateway's `sql_generation` route |
| Guardrail (governance layer, not an "agent" in name, but always in the loop) | Validates, rewrites, and allow/deny-gates every SQL candidate before it can touch the database |
| Read-only query executor | Runs guardrail-approved SQL against the read-only Postgres role and returns a `TableResult` |
| `AnalyticsAgentRunner` / `AnalyticsServiceRunner` | Forecasting and anomaly detection over the query result |
| `VisualizationAgentRunner` | Produces a `ChartSpec` for the frontend when the question is chart-shaped |
| `RagAgentRunner` | Runs hybrid retrieval (§8) and returns evidence for "why" / "explain" questions |
| `FederatedQueryAgent` | Extends read-only querying to admin-approved business data sources |
| `FileDataAgent` / `FileScopedRetriever` | Answers questions scoped to a user's uploaded file, respecting file ownership/sharing |
| `VerifierAgentRunner` / `AnswerAssemblyVerifier` | Checks the assembled answer against its sources before it is returned |

Why this shape, not one big prompt:

- **Guardrails sit between the model and the database.** SQL generation is a model call; SQL *execution* is not — it only happens after a separate, non-LLM guardrail decision (§7). A prompt injection or a hallucinated `DROP TABLE` cannot reach the database because the model never has execute access.
- **Each agent is independently testable.** `tests/test_sql_agent.py`, `tests/test_rag_agent.py`, `tests/test_analytics_agent.py`, `tests/test_verifier_agent.py`, etc. test one adapter's contract, not the whole pipeline end to end every time.
- **Confidence is aggregated, not asserted.** `ConfidenceAggregator` (`src/chatbi/orchestration/confidence.py`) combines signals from the agents that actually ran (SQL success, RAG hit quality, verifier outcome) into one score, weighted per source, instead of trusting a single model's self-reported confidence.
- **Async work is handed off, not blocked on.** Long-running analytics/RAG jobs go through `WorkerHandoffQueue` (`src/chatbi/orchestration/worker.py`) to a separate worker process (`Dockerfile.worker`), so a slow forecast doesn't hold the chat request open.
- **Every step is traced.** `AgentStepTracer` records per-agent-step timing, status, and errors independent of the final HTTP response, so a failure in one agent doesn't erase visibility into the others.

## 6. Semantic Layer and Governed NL2SQL

`src/chatbi/semantic/` sits between the raw question and SQL generation:

- `catalog.py` / `catalog_store.py` — the metric and table catalog the model is allowed to reference, so "revenue" resolves to one agreed definition, not whatever the model infers from a column name.
- `question_parser.py` — extracts structural intent (metric, dimension, time window, filters) before generation.
- `sql_generator.py` — builds the SQL candidate from the parsed question and catalog, routed through the LLM gateway's `sql_generation` task type.
- `schema_drift.py` — detects when the live database schema has moved away from what the catalog describes, so stale metric definitions get flagged rather than silently mis-answering.

The NL2SQL step never talks to the database directly — its only output is a SQL *candidate* that must clear the guardrail described next.

## 7. SQL Guardrail, Governance and Data Security

`src/chatbi/governance/` is the layer that makes "read-only" a system property, not a prompt instruction:

- **`SqlStatementValidator`** (`sql_validator.py`) parses the candidate and rejects anything that is not a simple, safe `SELECT` — no DDL, no DML, no multi-statement payloads.
- **`SqlObjectAccessPolicy`** (`policies.py`) plus **`business_table_catalog.py`** enforce an allow-list of tables and columns the query is permitted to touch.
- **`RowLimitRewriter`** (`sql_rewriter.py`) injects a row cap so no query can return unbounded data.
- **`QueryTimeoutPolicy`** (`timeout_policy.py`) bounds execution time.
- **`PiiResultMasker`** (`masking.py`, `masking_plan.py`) masks sensitive fields in the *result*, based on the caller's permissions, after execution.
- **`GuardrailAuditLog`** (`audit.py`, `audit_recorder.py`, `query_audit.py`) records every allow/deny decision, the SQL hash, and the reason — queryable later at `GET /api/v2/admin/query-audit/{audit_trace_id}` (admin-only).
- **`ReadOnlyQueryExecutor`** (`readonly_executor.py`, `readonly_probe.py`) executes only against `CHATBI_READONLY_DATABASE_URL` — a separate, DB-level read-only Postgres role (`docker/postgres/init`), so the guardrail is backed by a second layer at the database itself, not just application logic.

Defense in depth, concretely: even if the SQL guardrail had a bug, the database connection it executes against has no write privileges. Even if a write slipped through, the row it could touch is still scoped by the object-access policy. Every decision — allowed or denied — is written to an audit log tied to the request's `trace_id`.

## 8. RAG Design: Hybrid Retrieval

The RAG stack answers "why" / "explain" questions from real business documents (metric definitions, policies, operating reviews), not from the model's own guesses, and it is built as an honest hybrid pipeline rather than a vector-search-only shortcut.

### Why hybrid, not vector-only

Pure semantic search misses exact terms (product codes, ticket IDs, precise metric names) that keyword search catches, and pure keyword search misses paraphrases and synonyms that embeddings catch. The retrieval pipeline fuses both, then reranks:

```text
Document -> parse -> chunk -> embed -> pgvector (owner/role-scoped)

Question -> embed -> vector similarity search        \
         -> BM25 keyword score (rank-bm25)             > hybrid fusion -> top-2K
         -> tenant / owner / permission filter        /
                                                            |
                                                cross-encoder rerank (optional)
                                                            |
                                              citation-grounded context builder
                                                            |
                                                        LLM answer + citations
```

- **Embedding**: `EmbeddingClient` protocol (`src/chatbi/embedding_vector_rag.py`) with a `MockEmbeddingClient` for tests and an `OpenAIEmbeddingClient` (`embedding_vector_config.py`) for real deployments.
- **Keyword scoring**: real BM25 over the already permission-filtered candidate set — not a Jaccard/token-overlap stand-in.
- **Vector store**: `InMemoryVectorStore` for local/dev, and `PostgresKnowledgeVectorSource` on pgvector's `knowledge.doc_embeddings` for production, gated by `CHATBI_PGVECTOR_SEARCH_ENABLED`. Candidate rows are scoped by `owner_user_id` / `allowed_roles` **in the SQL itself**, not filtered after the fact in application code — the same class of tenant-leak bug is closed at the query level.
- **Reranking**: an optional cross-encoder pass (`sentence-transformers`, the `rerank` extra) re-scores the top-2K candidates a second time, gated by `CHATBI_RERANKER_ENABLED`, with a documented fallback to the pre-rerank ordering when the model isn't available — a reranker is a quality improvement, not a hard dependency.
- **Output shape**: every RAG answer carries `citations`, `evidence_chunks`, a `confidence` score, and an explicit `missing_evidence_warning` when nothing relevant was found — the system is designed to say "no evidence found" rather than invent one.

### Evaluating retrieval, not just the final answer

`golden_dataset/cases.json` is a real, schema-grounded, self-verified set of business questions with `expected_chunk_ids` — ground truth for "did retrieval find the right chunk," not just "did the final answer look plausible." `retrieval_evaluation.py` scores it with **Hit Rate@K** and **MRR**, tracked as observability-only metrics for now (no release-gate threshold yet, deliberately, until a real production baseline exists to set one against).

### How the design got here — an honest audit trail

This pipeline's design was revised after a code-level audit that found its documented four-stage shape (embed → chunk → hybrid score → rerank) already existed, but three of the four stages were placeholders: a hash-bucket pseudo-embedding standing in for real vectors on one code path, token-overlap standing in for BM25, and a "rerank" step that re-sorted a score already computed earlier rather than running a second model. Each gap was written up and closed as its own design (`system_design/final-version/en/04-followups/01`–`05`), then a further review pass found the reload path wasn't actually consuming the backfilled pgvector vectors, and that the golden dataset itself needed to be real content, not a synthetic fixture (`04-followups/06`). That history is kept in the repo rather than summarized away, because a system that documents its own gaps being found and closed is more credible than one that only documents intentions.

### Continuous improvement: golden-dataset mining

`golden_dataset_mining.py` mines real questions asked in production into candidate golden-dataset cases, reading from the observability log/trace stores. Those stores are in-memory by default; `CHATBI_OBSERVABILITY_POSTGRES_ENABLED` switches them to a durable Postgres-backed implementation so mining can run against a deployment's actual question history instead of only the current process's uptime — turning retrieval evaluation into a loop that improves from real usage, not a one-time fixture.

## 9. Model Selection: LLM and Embeddings

### Why a gateway, not direct SDK calls

`src/chatbi/llm/gateway.py` is the single place every model call goes through. It gives the system one place to enforce timeouts, retries with backoff, per-task model routing, and token/cost tracking — and one place to swap providers without touching agent code, because every provider implements the same `LLMProvider` protocol (`complete(request, route) -> LLMResponse`).

### Why mock-first, by default

`CHATBI_LLM_PROVIDER=mock` and `CHATBI_EMBEDDING_PROVIDER=mock` are the defaults (`.env.example`). `MockLLMProvider` is deterministic and network-free: same input, same output, no API key, no cost, no flakiness from a live model. That is a deliberate choice, not a placeholder left in by accident — it is what makes 195 test files and a CI release gate possible without every run costing money or depending on an external API's uptime. Agent contracts, guardrail behavior, and orchestration logic are verified against something deterministic; only the provider swap at the edge changes for a real deployment.

### Why OpenAI as the first real provider

`OpenAIChatProvider` is a deliberately minimal stdlib-HTTP adapter (no SDK dependency) so it doesn't add a heavy import to the baseline test path. The default routed model is `gpt-4o-mini` (`_llm_model_from_env` in `llm/config.py`) — chosen as the default because it balances cost and latency for a chat-analytics workload that makes several model calls per question (intent classification, SQL generation, answer synthesis) rather than one; `CHATBI_LLM_MODEL` overrides it per deployment. The same reasoning applies to `text-embedding-3-small` as the default embedding model: 1536 dimensions and low per-token cost, adequate for chunk-level semantic search where recall matters more than maximum embedding fidelity.

### Task-based routing, not one model for everything

The gateway routes by `task_type` (`intent_classification`, `sql_generation`, `answer_synthesis`, `evidence_reasoning`), so a deployment can point cheaper/faster models at classification and a stronger instruction-following model at SQL generation, independently, via configuration rather than code changes. Answer synthesis is explicitly grounded: it receives only the bounded SQL rows and evidence snippets actually returned upstream, and for "why"/"explain" questions it must cite the evidence's anchors rather than fall back to a generic summary — enforced by `tests/test_answer_synthesis.py`.

### Extending to other providers

Because `LLMProvider` and `EmbeddingClient` are protocols, adding Anthropic, Gemini, or a local model server is an adapter, not a rewrite of the orchestrator or agents — `providers.py` currently ships `MockLLMProvider` and `OpenAIChatProvider`; that list is the extension point.

## 10. Authentication, RBAC and Tenant Isolation

`src/chatbi/auth.py` implements real auth, not a stub:

- **Data model**: `auth.organizations`, `auth.users` (hashed passwords, roles, permissions, `token_version` for revocation), `auth.refresh_sessions` (hashed refresh tokens, expiry, revocation), `auth.role_audit_events` (every role/permission change, before/after, actor, target).
- **Tokens**: short-lived access tokens (15 min default) plus longer-lived refresh sessions (14 days default), issued via `POST /api/v2/auth/signup`, `signin`, `refresh`, and revoked via `POST /api/v2/auth/sessions/revoke`.
- **RBAC**: admin-only endpoints check specific permission strings (`admin:eval:read`, `admin:eval:write`, `admin:trace:read`, `admin:audit:read`, `admin:release_gate:read`, `admin:user:write`, …) rather than a single coarse "is_admin" flag, so an org can grant read access to observability without granting write access to user roles.
- **Tenant isolation**: `org_id` scopes query history, RAG documents/embeddings, evaluation results, audit logs, and traces. RAG's owner/role scoping (§8) is enforced in SQL, not filtered after retrieval — the design explicitly calls out closing that class of leak once, as a named acceptance criterion (a test that tenant/owner A cannot retrieve tenant/owner B's chunks).
- **Files**: uploaded files carry ownership and an explicit sharing model (`src/chatbi/files/sharing.py`, `POST /api/v2/files/{file_id}/share`) — only the owner or an admin in the same org can delete or manage sharing.

## 11. Observability, Auditing and Maintenance

- **Traces**: every chat query is traceable end to end by `trace_id` — API received, auth checked, orchestrator planned, SQL generated, guardrail checked, DB executed, RAG searched, answer synthesized, response returned (`GET /api/v2/governance/traces/{trace_id}`, admin-only).
- **Structured logs**: JSON logs carry `timestamp`, `level`, `trace_id`, `user_id`, `org_id`, `event_type`, `message`, `metadata`, with sensitive content masked before it is written.
- **Metrics**: request latency/error rate, LLM latency/token usage, guardrail block count, RAG hit rate, evaluation pass rate, and release-gate status, exposed at `/metrics` and summarized for operators at `GET /api/v2/admin/observability/summary`.
- **Durable storage, opt-in**: observability logs and traces are in-memory by default (fast, zero-config for local dev) and switch to a pooled, durable PostgreSQL-backed store when `CHATBI_OBSERVABILITY_POSTGRES_ENABLED=true`, with a configurable retention window (`CHATBI_OBSERVABILITY_RETENTION_DAYS`, default 30) and a scheduled sweep that prunes expired records — this is what makes golden-dataset mining (§8) possible against real deployment history instead of just the current process's uptime.
- **Maintenance loop**: the combination of durable observability + golden-dataset mining + retrieval Hit Rate/MRR evaluation is the platform's built-in feedback loop for improving RAG quality from real usage over time, rather than relying on manual spot checks.
- **Migrations**: `migrations.py` / `migrate.py` provide a CLI for schema evolution against the PostgreSQL instance.

## 12. Testing, Evaluation and Release Gates

- **Unit and integration tests**: 195 files under `tests/`, covering agent contracts, orchestration routing, guardrail rules, auth/RBAC/tenant isolation, RAG retrieval and hybrid scoring, file upload/sharing, frontend state/props contracts, Docker/Kubernetes architecture assertions, and more.
- **Static typing**: `pyright` in **strict** mode over both `src` and `tests` (`pyproject.toml`), plus dedicated architecture-boundary tests (`test_architecture_boundaries.py`, `test_backend_api_boundaries.py`) that assert layers don't reach past their intended dependencies.
- **Evaluation runner**: `EvalRunner` executes evaluation cases and produces `eval_run` / `eval_score` / `eval_failure` records and an `EvalRunReport`, exposed via `POST /api/v2/evals/run` and `GET /api/v2/evals/{eval_run_id}` (admin-only).
- **Release gate**: `release_gate.py` combines pytest, pyright, and evaluation-quality checks into a single pass/fail decision, surfaced at `GET /api/v2/release-gates/latest` and enforced in CI (`.github/workflows/spec-10-release-gate.yml`).
- **Human acceptance, after the machine gates**: `human_acceptance.py` requires a human sign-off, but deliberately *after* pytest/pyright/safety checks pass — business review cannot override a failed machine gate, it can only add judgment on top of one that already passed.
- **Retrieval-specific evaluation**: Hit Rate@K / MRR against the golden dataset (§8), tracked separately from answer-level evaluation.

## 13. Deployment

### Docker Compose (local)

```bash
docker compose up --build
```

| Service | Address |
|---|---|
| React frontend | `http://localhost:8080` |
| Backend API | `http://localhost:8000` |
| PostgreSQL | `localhost:5433` (mapped from container `5432`) |
| Redis | `localhost:6379` |

### Kubernetes

```bash
kubectl apply -f k8s/chatbi-runtime.yaml
```

The manifest defines a namespace, Deployments/Services for each component, an Ingress, and a HorizontalPodAutoscaler, and its shape is validated by `tests/test_k8s_runtime_architecture.py`. It has also been exercised against a real GKE staging cluster: `docs/deployment/cloud-kubernetes-runbook.md` documents the build/secrets/deploy path, and `scripts/generate_gke_staging_metrics.py`, `generate_gke_golden_correctness.py`, `generate_gke_extended_correctness.py`, `summarize_gke_concurrency.py`, and `summarize_gke_repeated_concurrency.py` reproduce the load, correctness, and repeated-run stability benchmarks; a pod-recovery drill (deleting a running backend pod and timing the rollout back to a healthy state) is included as well. This is staging-grade validation, not a production SLA — remaining hardening (managed Postgres/Redis, a real image registry, TLS on the ingress, a secrets manager, and environment overlays for prod vs. staging) is tracked in the runbook, and results from these scripts are local/ephemeral (written to the gitignored `dist/report/`), not committed as permanent claims.

## 14. API Surface

Selected endpoints (see `docs/api.md` for the full contract):

| Endpoint | Purpose |
|---|---|
| `GET /healthz`, `GET /readyz`, `GET /metrics` | Liveness, readiness, runtime metrics |
| `POST /api/v2/auth/signup` / `signin` / `refresh` / `sessions/revoke` | Auth lifecycle |
| `POST /api/v2/chat/query` | Main ChatBI query endpoint (auth-scoped) |
| `GET /api/v2/chat/history` | A user's own query history |
| `GET /api/v2/query/{trace_id}`, `GET /api/v2/requests/{trace_id}` | Query replay / detail |
| `POST /api/v2/analytics/analyze`, `POST /api/v2/analytics/tasks` | Analytics / forecasting |
| `POST /api/v2/documents/index` | RAG document ingestion |
| `POST /api/v2/files/upload`, `.../share` | File upload and sharing |
| `PUT /api/v2/admin/users/{user_id}/roles` | Admin: change a user's roles (audited) |
| `GET /api/v2/admin/audits/roles` | Admin: role-change audit log |
| `GET /api/v2/admin/query-audit/{audit_trace_id}` | Admin: SQL guardrail decision detail |
| `GET /api/v2/governance/traces/{trace_id}` | Admin: full trace detail |
| `POST /api/v2/evals/run`, `GET /api/v2/evals/{eval_run_id}` | Admin: run/read evaluations |
| `GET /api/v2/release-gates/latest` | Admin: release-gate status |
| `GET /api/v2/admin/observability/summary` | Admin: aggregated ops dashboard |

## 15. Repository Map

| Path | Purpose |
|---|---|
| `src/chatbi/api/` | FastAPI adapter and API payload models |
| `src/chatbi/application/` | Application facade coordinating domain workflows |
| `src/chatbi/orchestration/` | Agent routing, execution planning, tracing, state |
| `src/chatbi/agents/` | SQL, RAG, analytics, visualization, verifier, file, federated-query agents |
| `src/chatbi/semantic/` | Semantic catalog, question parsing, NL2SQL helpers |
| `src/chatbi/governance/` | SQL guardrails, policies, audit, masking, read-only execution |
| `src/chatbi/llm/` | LLM provider gateway, routing, types, providers |
| `src/chatbi/rag*.py`, `embedding_vector_rag.py` | RAG contracts, indexing, hydration, hybrid retrieval, worker |
| `src/chatbi/golden_dataset*.py` | Golden dataset cases and mining pipeline |
| `src/chatbi/auth.py` | Auth, RBAC, tenant context |
| `src/chatbi/analytics*.py` | Analytics, forecasting, persistence, async worker |
| `src/chatbi/observability*.py` | Spans, logs, durable Postgres storage, retention |
| `src/chatbi/evaluation*.py` | Evaluation scoring, persistence, reports, benchmarks |
| `src/chatbi/files/` | Upload, chunked upload, storage, sharing, retention |
| `src/chatbi/frontend/` | Frontend state, props, fixtures, static build |
| `frontend/` | React + Vite chat UI and admin console |
| `spec/`, `system_design/` | Versioned specs and system design docs (v1, v2, final-version, EN/中文) |
| `verification/` | Per-spec verification reports |
| `k8s/`, `docker-compose.yml`, `Dockerfile.*` | Deployment scaffolding |
| `.github/workflows/` | CI release gate |

## 16. Local Development

```bash
# Python environment
python -m venv .venv313
.venv313/bin/python -m pip install --upgrade pip
.venv313/bin/python -m pip install -e ".[dev]"

# Focused tests
.venv313/bin/python -m pytest tests/test_app.py tests/test_http_app.py

# Full suite
.venv313/bin/python -m pytest

# Strict static checks
.venv313/bin/python -m pyright src tests

# Local stack
docker compose up --build
```

## 17. Engineering Decision Log

- SQL execution is read-only and guardrail-checked before it ever reaches the database, and the read-only role is enforced again at the database level.
- `trace_id` is a first-class identifier threaded through backend, orchestrator, audit, evaluation, and logs.
- Core agent workflows have deterministic tests (mock LLM/embedding providers) so release gates stay stable and don't depend on a live model.
- New capabilities (reranker, pgvector search, durable observability) ship behind explicit opt-in flags, off by default — enabling them is a deliberate operator action, not an automatic behavior change on deploy.
- Evaluation runner, repository, and report read-model are kept as separate layers so release quality stays explainable.
- Human acceptance happens after machine gates, never instead of them.
- Gaps found during design/code audits (RAG placeholders, tenant-leak risk, embedding-reload bug) are documented and closed as named follow-up specs, not silently patched.

## 18. Current Status and Roadmap

Implemented and tested today: multi-agent orchestration, semantic layer and NL2SQL, SQL guardrail and governance, real auth/RBAC/tenant isolation, LLM provider gateway (mock + OpenAI), hybrid RAG (real BM25 + embeddings + optional cross-encoder rerank + pgvector with owner/role scoping), a golden dataset with Hit Rate/MRR retrieval evaluation, golden-dataset mining from real usage, durable opt-in observability storage, evaluation runner and release gate with a human-acceptance step, Docker Compose runtime, and a Kubernetes manifest (Ingress + HPA) exercised against a real GKE staging cluster with load, correctness, and pod-recovery benchmarks.

Still ahead before this is a full production cloud service:

| Area | Gap | Direction |
|---|---|---|
| Cloud deployment | Deployed and benchmarked on a GKE staging cluster (Ingress, HPA, secrets, load/correctness/pod-recovery benchmarks); not yet a hardened production profile | Managed Postgres/Redis, a real image registry, TLS on the ingress, a secrets manager for all environments, and prod-vs-staging overlays |
| Distributed resilience | Timeout/retry/idempotency pieces exist; no circuit breaker, DLQ, or bulkheads yet | Circuit breaker, backoff, queue DLQ, load shedding, chaos/load tests |
| Additional LLM/embedding providers | OpenAI is the only real provider implemented | Anthropic/Gemini adapters behind the existing `LLMProvider`/`EmbeddingClient` protocols |
| Large-scale data | Sample/demo data exists; not yet enough for realistic load testing | Synthetic enterprise dataset generator and seed pipeline |
| External APM | Internal traces/logs/metrics exist; no external exporter yet | OpenTelemetry/Prometheus/Grafana integration |

## 19. Documentation Index

- Final-version specs: [spec/final-version/README.md](../../spec/final-version/README.md)
- Final-version system design: [system_design/final-version/README.md](../../system_design/final-version/README.md)
- API documentation: [docs/api.md](../api.md)
- Local startup guide: [docs/local-startup.md](../local-startup.md)
- Cloud deployment runbook: [docs/deployment/cloud-kubernetes-runbook.md](../deployment/cloud-kubernetes-runbook.md)
- Demo script: [docs/demo-script.md](../demo-script.md)
- Risk register: [docs/risk-register.md](../risk-register.md)
- Verification reports: [verification/](../../verification/)
