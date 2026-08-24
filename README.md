# Governed Multi-Agent ChatBI Platform

**InsightOps AI** is a governed, multi-agent ChatBI platform for enterprise decision intelligence: a business user asks a question in natural language, and the system routes it through specialized agents for semantic interpretation, governed SQL generation, read-only execution, RAG evidence retrieval, analytics/forecasting, and answer verification — with every step traced, audited, and gated by an evaluation/release process.

Full write-ups: [English deep dive](docs/readme/README.en.md) · [中文完整版](docs/readme/README.zh-CN.md) · [Academic report (LaTeX/PDF)](report/InsightOps_AI_Report.tex)

## Who It's For

| Persona | Gets |
|---|---|
| Business user | Natural-language chat, grounded answers with citations and charts, no visibility into other users' data |
| Analyst | Shared team history, a semantic metric catalog, evidence-backed answers |
| Data / platform team | SQL guardrail audit trail, PII masking, a database-level read-only role, per-tenant isolation |
| Admin | An admin console behind `admin:*` permissions: traces, evaluations, release-gate status, role-change audit log |
| Engineering reviewer | 195 test files, strict `pyright`, layered architecture with boundary tests, and a documented history of design gaps being found and closed |

## What's Actually Implemented

This is not a thin LLM wrapper. The following are implemented and covered by tests today:

- **Multi-agent orchestration** — a question classifier and execution-plan builder route each question to the right combination of SQL, RAG, analytics, visualization, verifier, file, and federated-query agents, executed and traced step by step (`src/chatbi/orchestration/`, `src/chatbi/agents/`).
- **Governed NL2SQL** — a semantic catalog constrains what the model can reference; every generated SQL candidate must clear a guardrail (statement validator, table/column allow-list, row-limit rewriter, timeout policy) before it can touch a database, and it only ever executes against a separate, database-level read-only role (`src/chatbi/semantic/`, `src/chatbi/governance/`).
- **Real authentication and RBAC** — organizations, users, hashed passwords, access/refresh tokens, permission-scoped admin endpoints, and an audited role-change log; tenant isolation (`org_id`) scopes history, documents, evaluations, and traces (`src/chatbi/auth.py`).
- **Hybrid RAG** — real BM25 keyword scoring fused with real embeddings, an optional cross-encoder rerank pass, and a pgvector-backed production vector store with SQL-level owner/role scoping — plus a golden dataset with Hit Rate/MRR retrieval evaluation, and a mining pipeline that turns real production questions into future evaluation cases (`src/chatbi/embedding_vector_rag.py`, `src/chatbi/rag*.py`, `src/chatbi/golden_dataset*.py`).
- **LLM provider gateway** — a provider-agnostic interface with task-based model routing, timeouts/retries, and token/cost tracking; a deterministic mock provider by default (for cost-free, network-free CI) and a real OpenAI adapter for production (`src/chatbi/llm/`).
- **Evaluation and release gates** — an evaluation runner, `pytest` + strict `pyright` checks, and a release-gate decision that a human can accept *after* the machine gates pass, never instead of them (`src/chatbi/evaluation*.py`, `src/chatbi/release_gate.py`, `.github/workflows/spec-10-release-gate.yml`).
- **Observability with a maintenance loop** — traces, masked structured logs, runtime metrics, an admin observability summary, and an opt-in durable Postgres-backed store with retention sweeps that make golden-dataset mining possible against real usage history (`src/chatbi/observability*.py`).
- **Deployable and staging-tested** — Docker Compose for local development, and a Kubernetes manifest (namespace, Deployments, Services, Ingress, HPA) with a reproducible GKE staging runbook and load/failover benchmark scripts, not just an unexercised YAML file (`docker-compose.yml`, `k8s/chatbi-runtime.yaml`, `docs/deployment/cloud-kubernetes-runbook.md`, `scripts/generate_gke_*.py`).

See the [English deep dive](docs/readme/README.en.md) for the full architecture diagram, the RAG design rationale (including an honest audit trail of gaps that were found and closed), why the LLM/embedding models were chosen, the SQL guardrail's defense-in-depth model, and the remaining gaps before this is a full production cloud service (managed-cloud hardening beyond staging, distributed resilience like circuit breakers/DLQ, additional LLM providers, large-scale synthetic data, external APM).

## Technology Stack

Python 3.11+ / FastAPI backend, PostgreSQL 16 + pgvector, Redis, React + Vite + TypeScript frontend, BM25 + embeddings + optional cross-encoder hybrid retrieval, an OpenAI-backed LLM/embedding gateway with a deterministic mock fallback, Docker Compose + Kubernetes (GKE-tested), `pytest` (195 test files) + strict `pyright` + a GitHub Actions release gate.

## How to Use

1. **Set up the Python environment**

   ```bash
   python -m venv .venv313
   .venv313/bin/python -m pip install --upgrade pip
   .venv313/bin/python -m pip install -e ".[dev]"
   ```

2. **Start the local stack** (frontend `:8080`, backend `:8000`, PostgreSQL `:5433`, Redis `:6379`)

   ```bash
   cp .env.example .env   # fill in real values before a non-local run
   docker compose up --build
   ```

3. **Use the chat UI**, or drive the API directly:

   ```bash
   # Create an account (returns access_token/refresh_token)
   curl -X POST http://localhost:8000/api/v2/auth/signup \
     -H "Content-Type: application/json" \
     -d '{"email":"you@example.com","password":"ChangeMe123!","display_name":"Demo User","organization_name":"Acme Analytics"}'

   # Ask a governed ChatBI question (use the access_token from above)
   curl -X POST http://localhost:8000/api/v2/chat/query \
     -H "Authorization: Bearer <access_token>" \
     -H "Content-Type: application/json" \
     -d '{"session_id":"demo-session-1","question":"What was our highest-revenue month?","locale":"en","role":"analyst"}'
   ```

   The response carries a `trace_id`. Look it up (as an admin) at
   `GET /api/v2/governance/traces/{trace_id}` to see every step the request
   went through: auth, SQL generation, guardrail decision, execution, and
   answer synthesis.

4. **Try the admin console** by signing in as a user with an `admin` role
   and opening the Admin tab in the frontend, or calling
   `GET /api/v2/admin/observability/summary` directly — it surfaces system
   health, LLM/token/cost signals, guardrail blocks, RAG hit rate,
   evaluation results, and release-gate status.

5. **Walk a scripted 15-minute demo** covering sign-in, chat, RAG citations,
   the admin console, and the release gate: [docs/demo-script.md](docs/demo-script.md).
   Full endpoint contracts: [docs/api.md](docs/api.md). Step-by-step local
   setup: [docs/local-startup.md](docs/local-startup.md).

## How to Test

| What | Command | Notes |
|---|---|---|
| Full test suite | `.venv313/bin/python -m pytest` | 195 files, mock LLM/embedding providers — no API key or network needed |
| One focused slice | `.venv313/bin/python -m pytest tests/test_app.py tests/test_http_app.py` | Fast smoke check of the app + HTTP layer |
| Release-gate slice | see [docs/readme/README.en.md §12](docs/readme/README.en.md#12-testing-evaluation-and-release-gates) | The exact test set CI runs before a release is gated |
| Static typing | `.venv313/bin/python -m pyright src tests` | Strict mode across source and tests, incl. architecture-boundary checks |
| Local stack smoke test | `docker compose up --build`, then hit `/healthz`, `/readyz`, `/api/v2/chat/query` | Verifies the containerized topology, not just unit tests |
| Evaluation runner | `POST /api/v2/evals/run` (admin token) or `EvalRunner` in `src/chatbi/evaluation.py` | Produces run/score/failure records and a release-gate-visible report |
| Retrieval quality (Hit Rate@K, MRR) | `src/chatbi/retrieval_evaluation.py` against `src/chatbi/golden_dataset/cases.json` | Scores retrieval itself, not just the final answer |
| CI on every push | [.github/workflows/spec-10-release-gate.yml](.github/workflows/spec-10-release-gate.yml) | Runs the release-gate bundle automatically |
| Cloud/staging load & failover benchmarks | `scripts/generate_gke_staging_metrics.py --base-url <url>`, `scripts/generate_gke_golden_correctness.py`, `scripts/generate_gke_extended_correctness.py`, `scripts/summarize_gke_concurrency.py`, `scripts/summarize_gke_repeated_concurrency.py` | Require a live GKE deployment (see the runbook below); this is how the platform's concurrency, pod-recovery, and correctness benchmarks against a real cluster are reproduced. Output lands in `dist/report/` (gitignored — regenerate locally rather than expecting it committed) |
| CI for the cloud deployment path | [.github/workflows/fv07-cloud-deployment.yml](.github/workflows/fv07-cloud-deployment.yml) | Builds/tests images and can trigger a staging deploy |

Baseline tests use mock/deterministic LLM and embedding providers by
design (see [docs/readme/README.en.md §9](docs/readme/README.en.md#9-model-selection-llm-and-embeddings)
for why) — they do not require a real OpenAI key or network access.

## Links

### Specs and System Design

| Artifact | Link |
|---|---|
| Spec master index (how to read a spec, v1 → v2 → final) | [spec/index.md](spec/index.md) |
| Final specs index | [spec/final-version/README.md](spec/final-version/README.md) |
| English final specs | [spec/final-version/en/README.en.md](spec/final-version/en/README.en.md) |
| Chinese final specs | [spec/final-version/zh-CN/README.zh-CN.md](spec/final-version/zh-CN/README.zh-CN.md) |
| System design index (EN) | [system_design/system-design-index.en.md](system_design/system-design-index.en.md) |
| System design index (中文) | [system_design/system-design-index.zh-CN.md](system_design/system-design-index.zh-CN.md) |
| Final-version system design (EN) | [system_design/final-version/en/README.en.md](system_design/final-version/en/README.en.md) |
| Final-version system design (中文) | [system_design/final-version/zh-CN/README.zh-CN.md](system_design/final-version/zh-CN/README.zh-CN.md) |
| RAG design + follow-up audit trail (the honest "what was a placeholder, and how it was closed" history) | [system_design/final-version/en/04-followups/README.en.md](system_design/final-version/en/04-followups/README.en.md) |

### Project Plan / Roadmap

| Artifact | Link |
|---|---|
| Executive system design (positioning, principles, what the final version must prove) | [system_design/final-version/en/00-executive-system-design.en.md](system_design/final-version/en/00-executive-system-design.en.md) |
| Final delivery roadmap (the project plan the final-version specs are derived from) | [system_design/final-version/en/09-final-delivery-roadmap.en.md](system_design/final-version/en/09-final-delivery-roadmap.en.md) |
| Final delivery roadmap (中文) | [system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md](system_design/final-version/zh-CN/09-final-delivery-roadmap.zh-CN.md) |
| Risk register | [docs/risk-register.md](docs/risk-register.md) |
| Final submission checklist | [verification/12-final-submission-package-verification.md](verification/12-final-submission-package-verification.md) |

### Diagrams and Architecture

| Artifact | Link |
|---|---|
| Architecture, guardrail decision flow, and hybrid RAG pipeline diagrams (rendered figures) | [report/InsightOps_AI_Report.tex](report/InsightOps_AI_Report.tex) (compiled PDF alongside it) |
| RAG retrieval flow (Mermaid) | [system_design/final-version/en/04-embedding-vector-rag.en.md](system_design/final-version/en/04-embedding-vector-rag.en.md) |
| Per-module design docs (architecture, orchestration, semantic layer, guardrail, data model, backend API, frontend, RAG, analytics, evaluation) | [system_design/](system_design/) |
| Folder structure map | [docs/folder-structure.md](docs/folder-structure.md) |

### Reports and Benchmarks

| Artifact | Link |
|---|---|
| Academic report (LaTeX source, IEEEtran format) | [report/InsightOps_AI_Report.tex](report/InsightOps_AI_Report.tex) |
| Compiled report PDF | `report/InsightOps_AI_Report.pdf` (build with `tectonic report/InsightOps_AI_Report.tex`) |
| Local baseline benchmark generator (accuracy, guardrail, concurrency, hallucination) | `scripts/generate_report_metrics.py` → `dist/report/report-metrics.md` |
| GKE staging benchmark generators (load, concurrency sweep, repeated-run stability, golden/extended correctness, pod-recovery drill) | `scripts/generate_gke_*.py`, `scripts/summarize_gke_*.py` — see [How to Test](#how-to-test) |
| Cloud deployment runbook (how the staging benchmarks above were produced) | [docs/deployment/cloud-kubernetes-runbook.md](docs/deployment/cloud-kubernetes-runbook.md) |
| Per-spec verification reports | [verification/](verification/) |

### Data and Examples

| Artifact | Link |
|---|---|
| Golden dataset (real, schema-grounded RAG evaluation cases) | `src/chatbi/golden_dataset/cases.json` |
| Demo seed data (SQL) | `scripts/seed_demo_data.sql` |
| Synthetic data expansion for load testing | `scripts/expand_demo_data.py` |
| Example RAG v2 workflow script | `examples/rag_v2_demo.py` |
| Example CSV for file-upload/hybrid analysis | `examples/regional_sales_h1_2026.csv` |

### API and Deployment

| Artifact | Link |
|---|---|
| Full README (English) | [docs/readme/README.en.md](docs/readme/README.en.md) |
| 完整 README（中文） | [docs/readme/README.zh-CN.md](docs/readme/README.zh-CN.md) |
| API documentation | [docs/api.md](docs/api.md) |
| Local startup guide | [docs/local-startup.md](docs/local-startup.md) |
| Demo script | [docs/demo-script.md](docs/demo-script.md) |
| Cloud (GKE) deployment runbook | [docs/deployment/cloud-kubernetes-runbook.md](docs/deployment/cloud-kubernetes-runbook.md) |
| Kubernetes manifest (namespace, Deployments, Services, Ingress, HPA) | [k8s/chatbi-runtime.yaml](k8s/chatbi-runtime.yaml) |
| Cloud deployment CI workflow | [.github/workflows/fv07-cloud-deployment.yml](.github/workflows/fv07-cloud-deployment.yml) |
| Release-gate CI workflow | [.github/workflows/spec-10-release-gate.yml](.github/workflows/spec-10-release-gate.yml) |
