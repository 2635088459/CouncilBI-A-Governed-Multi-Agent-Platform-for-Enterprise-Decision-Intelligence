# Local Startup Guide

Baseline local verification uses deterministic providers, so no real LLM API key
is required.

## 1. Python Environment

```bash
python -m venv .venv313
.venv313/bin/python -m pip install --upgrade pip
.venv313/bin/python -m pip install -e ".[dev]"
```

## 2. Required Services

For pure unit/integration tests, external services are optional because local
stores and mock providers are used.

Run the React + Vite frontend directly during UI development:

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api`, `/healthz`, `/readyz`, and `/metrics` to
`http://localhost:8000`. The Docker frontend uses nginx to proxy the same paths
to the `backend` service so browser calls stay same-origin.

For Docker Compose, provide database secrets through environment variables:

```bash
export POSTGRES_PASSWORD="<local-postgres-password>"
export CHATBI_READONLY_PASSWORD="<local-readonly-password>"
export DATABASE_URL="postgresql://chatbi:${POSTGRES_PASSWORD}@postgres:5432/chatbi"
export CHATBI_READONLY_DATABASE_URL="postgresql://chatbi_readonly:${CHATBI_READONLY_PASSWORD}@postgres:5432/chatbi"
docker compose up --build
```

Expected local services:

- React frontend: `http://localhost:8080`
- backend API: `http://localhost:8000`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

## 3. Seed Data

Generate deterministic final-version seed data:

```bash
.venv313/bin/python -m chatbi.final_seed --profile small --output-json /tmp/chatbi-small-seed.json
.venv313/bin/python -m chatbi.final_seed --validate-json /tmp/chatbi-small-seed.json
```

## 4. Tests

```bash
.venv313/bin/pyright src/chatbi
.venv313/bin/python -m pytest
```

Focused release checks:

```bash
.venv313/bin/python -m pytest tests/test_release_gate.py tests/test_release_gate_ci.py
.venv313/bin/python -m pytest tests/test_cloud_secret_scan.py tests/test_runtime_latency_smoke.py
```

## 5. Demo Flow

Follow [demo-script.md](demo-script.md) after Docker Compose or the backend plus
Vite frontend are running. The script covers sign-in, chat query, RAG citation,
admin observability, and release gate from the React UI or the API.
