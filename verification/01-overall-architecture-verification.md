# Verification: 01 Overall Architecture v2

This document records the current machine-verifiable status for
`spec/version2/01-overall-architecture.spec.md`.

## Verified Runtime Slice

```text
ChatQueryRequestV2
  -> POST /api/v2/chat/query
  -> ChatBIApplication
  -> SimpleOrchestrator
  -> RequestMetadataStore
  -> ChatQueryResponseV2
```

Runtime and deployment artifacts now include:

- `docker-compose.yml`
- `k8s/chatbi-runtime.yaml`
- `/healthz`, `/readyz`, and `/metrics`
- `RuntimeConfig`
- `InMemoryRequestMetadataStore`
- `PostgresRequestMetadataStore`
- `PsycopgRequestMetadataConnection` adapter
- `DatabaseReadinessChecker`

## Coverage Matrix

| ID | Status | Verification |
|---|---|---|
| `VR-01-001` | Covered | `tests/test_frontend_api_client.py`, `tests/test_docker_compose_architecture.py`, `tests/test_k8s_runtime_architecture.py`, `tests/test_architecture_boundaries.py` |
| `VR-01-002` | Covered for v2 HTTP + metadata | `tests/test_v2_chat_query_http.py` |
| `VR-01-003` | Covered | `tests/test_runtime_probes.py` |
| `VR-01-004` | Covered | `tests/test_v2_chat_query_http.py`, `tests/test_runtime_latency_smoke.py` |
| `VR-01-005` | Covered | `tests/test_architecture_boundaries.py` |
| `FR-01-001` | Covered statically | `docker-compose.yml`, `tests/test_docker_compose_architecture.py` |
| `FR-01-002` | Covered | `tests/test_v2_chat_query_http.py` |
| `FR-01-003` | Covered with optional live test | In-memory request metadata path, PostgreSQL repository, and live PostgreSQL integration entrypoint: `tests/test_v2_chat_query_http.py`, `tests/test_request_metadata_store.py`, `tests/test_postgres_metadata_integration.py` |
| `FR-01-004` | Covered | `src/chatbi/core/runtime_config.py`, `tests/test_runtime_config.py`, compose/K8s config tests |
| `FR-01-005` | Covered statically | `k8s/chatbi-runtime.yaml`, `tests/test_k8s_runtime_architecture.py` |
| `FR-01-006` | Covered | `/readyz` fails when database configuration is absent and uses `DatabaseReadinessChecker` for a live `SELECT 1` ping when PostgreSQL metadata mode is enabled. See `tests/test_runtime_probes.py`, `tests/test_runtime_config.py` |
| `NFR-01-001` | Covered as local smoke | `tests/test_runtime_latency_smoke.py` |
| `NFR-01-002` | Covered as local smoke | `tests/test_runtime_latency_smoke.py` |
| `NFR-01-003` | Covered | `tests/test_v2_chat_query_http.py`, `tests/test_observability_logs.py` |
| `NFR-01-004` | Covered for added v2 architecture modules | Pyright commands listed below |
| `AC-01-001` | Covered | `tests/test_v2_chat_query_http.py` |
| `AC-01-002` | Covered | `tests/test_v2_chat_query_http.py` |
| `AC-01-003` | Covered | `/healthz` remains 200 while `/readyz` returns 503 when the database ping fails |
| `AC-01-004` | Covered when `DATABASE_URL` is provided | Optional live PostgreSQL test inserts, updates, and selects by `trace_id`: `tests/test_postgres_metadata_integration.py` |
| `AC-01-005` | Covered | `tests/test_docker_compose_architecture.py`, `tests/test_k8s_runtime_architecture.py` |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Focused v2 architecture tests:

```bash
.venv/bin/pytest \
  tests/test_v2_chat_query_http.py \
  tests/test_request_metadata_store.py \
  tests/test_runtime_config.py \
  tests/test_runtime_probes.py \
  tests/test_runtime_latency_smoke.py \
  tests/test_docker_compose_architecture.py \
  tests/test_k8s_runtime_architecture.py \
  tests/test_architecture_boundaries.py \
  tests/test_observability_logs.py \
  tests/test_postgres_metadata_integration.py
```

Recent result:

```text
60 passed, 1 skipped, 1 warning
```

Static type checks used while building this slice:

```bash
.venv/bin/pyright \
  src/chatbi/core/architecture_contracts.py \
  src/chatbi/core/runtime_config.py \
  src/chatbi/history/request_metadata.py \
  src/chatbi/api/http.py \
  src/chatbi/observability_logs.py \
  tests/test_v2_chat_query_http.py \
  tests/test_request_metadata_store.py \
  tests/test_runtime_config.py \
  tests/test_runtime_probes.py \
  tests/test_runtime_latency_smoke.py \
  tests/test_docker_compose_architecture.py \
  tests/test_k8s_runtime_architecture.py \
  tests/test_architecture_boundaries.py \
  tests/test_observability_logs.py \
  tests/test_postgres_metadata_integration.py
```

Recent result:

```text
0 errors, 0 warnings, 0 informations
```

## Remaining Gaps

The following items are intentionally not fully complete yet:

- `AC-01-004` has a live PostgreSQL test entrypoint, but it is skipped unless `DATABASE_URL` is provided.
- Docker Compose is statically verified, but not runtime-validated in this environment because `docker` was unavailable.
- Kubernetes manifests are statically verified, but not runtime-validated in this environment because `kubectl` was unavailable.

## Next Recommended Step

Run the optional live PostgreSQL verification in Docker or another PostgreSQL runtime:

```text
DATABASE_URL=postgresql://...
  .venv/bin/pytest tests/test_postgres_metadata_integration.py -q
```
