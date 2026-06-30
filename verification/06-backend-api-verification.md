# Verification: 06 Backend API v2

This document records the current machine-verifiable status for
`spec/version2/06-backend-api.spec.md`.

## Scope

Verified runtime slice:

```text
Frontend-facing HTTP request
  -> FastAPI route
  -> bearer/header/request validation
  -> v1 or v2 ApiEnvelope
  -> ChatBIApplication
  -> SimpleOrchestrator
  -> optional read-only query execution
  -> request metadata / runtime query result / audit records
  -> credential-safe error response

Runtime probes
  -> /healthz process liveness
  -> /readyz PostgreSQL, Redis, and read-only write-probe readiness
  -> /metrics Prometheus text

Long-running work
  -> document indexing request
  -> WorkerHandoffQueue task id
  -> task status lookup
  -> queued, running, succeeded, and failed task states
```

Covered API surface:

| Endpoint | Status |
|---|---|
| `POST /api/v1/chat/query` | Implemented and covered |
| `GET /api/v1/chat/tasks/{task_id}` | Implemented and covered |
| `GET /api/v1/chat/history` | Implemented with cursor pagination |
| `GET /api/v1/query/{trace_id}` | Implemented for trace replay |
| `GET /api/v1/metrics/catalog` | Implemented from governed catalog metadata |
| `GET /api/v1/datasets/catalog` | Implemented from data model catalog |
| `POST /api/v1/documents/index` | Implemented with async task handoff and idempotency |
| `POST /api/v1/sql/preview` | Implemented as non-executing SQL preview |
| `POST /api/v1/sql/guardrail/check` | Implemented for guardrail decision preview |
| `GET /api/v1/audit/{trace_id}` | Implemented from API audit records |
| `GET /api/v1/observability/traces/{trace_id}` | Implemented |
| `POST /api/v1/evals/run` | Implemented as in-process evaluation smoke run |
| `GET /api/v1/quality/dashboard` | Implemented |
| `GET /api/v1/health` | Implemented as authenticated v1 envelope health check |
| `POST /api/v2/chat/query` | Implemented and covered |
| `GET /api/v2/chat/history` | Implemented and covered |
| `GET /api/v2/query/{trace_id}` | Implemented with public trace id replay |
| `GET /api/v2/requests/{trace_id}` | Implemented for request metadata lookup |
| `GET /api/v2/chat/tasks/{task_id}` | Implemented and covered |
| `POST /api/v2/documents/index` | Implemented with async task handoff and idempotency |
| `GET /api/v2/query-results/{trace_id}` | Implemented without returning plaintext SQL |
| `GET /api/v2/governance/traces/{trace_id}` | Implemented as request/result/guardrail summary |
| `GET /api/v2/metrics/catalog` | Implemented and covered |
| `GET /api/v2/datasets/catalog` | Implemented and covered |
| `GET /api/v2/health` | Implemented and covered |
| `GET /api/v2/ready` | Implemented and covered |
| `GET /healthz` | Implemented public liveness probe |
| `GET /readyz` | Implemented dependency readiness probe |
| `GET /metrics` | Implemented Prometheus text endpoint |

## Covered Requirements

| Requirement | Verification |
|---|---|
| `VR-06-001` | v1 and v2 API responses use envelope shapes. See `tests/test_http_app.py` and `tests/test_v2_chat_query_http.py`. |
| `VR-06-002` | Controller raw SQL execution boundary is checked by `tests/test_backend_api_boundaries.py`. |
| `VR-06-003` | Missing or invalid request bodies return validation envelopes. v2 FastAPI validation errors are also normalized to the v2 envelope. |
| `VR-06-004` | `/readyz` fails when PostgreSQL, Redis, or the read-only write probe is unavailable. See `tests/test_runtime_probes.py`. |
| `VR-06-005` | Long-running task status is queryable by `task_id` for v1 and v2. See `tests/test_http_app.py`, `tests/test_v2_chat_query_http.py`, and `tests/test_worker_handoff.py`. |
| `FR-06-001` | `POST /api/v1/chat/query` is covered by `tests/test_http_app.py`. |
| `FR-06-002` | `GET /api/v1/chat/tasks/{task_id}` is covered by `tests/test_http_app.py`. |
| `FR-06-003` | `GET /api/v1/chat/history` is covered by `tests/test_http_app.py`. |
| `FR-06-004` | `GET /api/v1/query/{trace_id}` is covered by `tests/test_http_app.py`. |
| `FR-06-005` | `GET /api/v1/metrics/catalog` is covered by `tests/test_http_app.py`. |
| `FR-06-006` | `GET /healthz`, `GET /readyz`, and `GET /metrics` are covered by `tests/test_runtime_probes.py`. |
| `NFR-06-003` | Internal API errors return sanitized envelopes without stack traces, database credentials, passwords, or raw secret text. |
| `NFR-06-004` | Focused pyright check for Backend API files returns 0 errors with the clean Python 3.13 environment. |

## Acceptance Criteria

| Acceptance Criterion | Verification |
|---|---|
| `AC-06-001` | Valid chat query returns an envelope with `trace_id`, `request_id`, answer text, table result, and SQL preview/result fields. |
| `AC-06-002` | Invalid chat query returns validation envelope. v2 missing fields return `error.code == "VALIDATION_ERROR"`. |
| `AC-06-003` | History endpoint returns records ordered by `created_at desc` with cursor pagination. |
| `AC-06-004` | Unknown trace id returns 404-style not-found envelope for replay/detail endpoints. |
| `AC-06-005` | Readiness fails when Redis probe fails. |

## Test Plan Mapping

| Test Case | Current Verification |
|---|---|
| `TC-06-001` | Focused pyright check covers `src/chatbi/api` and the relevant Backend API tests. |
| `TC-06-002` | `tests/test_http_app.py` and `tests/test_v2_chat_query_http.py` verify valid chat query envelopes. |
| `TC-06-003` | `tests/test_http_app.py` and `tests/test_v2_chat_query_http.py` verify negative validation behavior. |
| `TC-06-004` | `tests/test_http_app.py` and `tests/test_v2_chat_query_http.py` verify history pagination and envelope shape. |
| `TC-06-005` | `tests/test_http_app.py` and `tests/test_v2_chat_query_http.py` verify unknown trace/task lookup behavior. |
| `TC-06-006` | `tests/test_runtime_probes.py` verifies Redis readiness failure. |
| `TC-06-007` | Local latency smoke coverage exists in `tests/test_runtime_latency_smoke.py`; this focused verification did not rerun the latency suite. |
| `TC-06-008` | `tests/test_http_app.py` and `tests/test_v2_chat_query_http.py` verify sanitized internal errors. |

## Design Notes

The Backend API keeps responsibilities separated:

1. `src/chatbi/api/models.py` defines public v1 request and response contracts.
2. `src/chatbi/core/architecture_contracts.py` defines stricter v2 envelope contracts.
3. `src/chatbi/api/http.py` handles HTTP routing, headers, request validation, status codes, readiness probes, and v1/v2 envelope translation.
4. `src/chatbi/application/app.py` owns application behavior such as idempotency, history, catalog lookup, rate limiting, and API audit records.
5. `src/chatbi/orchestration/worker.py` owns async task state transitions for queued, running, succeeded, and failed work.

In plain terms: `http.py` is the front desk, `app.py` is the service desk, the orchestrator does the analysis work, and the worker queue is the ticket counter for long-running jobs.

## Latest Local Verification

Environment:

```text
Virtual environment: .venv313
Python: 3.13.13
```

Focused Backend API boundary/runtime suite:

```bash
.venv313/bin/python -m pytest \
  tests/test_backend_api_boundaries.py \
  tests/test_worker_handoff.py \
  tests/test_runtime_config.py \
  -q
```

Result:

```text
19 passed
```

Focused Backend API HTTP/readiness suite:

```bash
.venv313/bin/python -m pytest \
  tests/test_http_app.py \
  tests/test_v2_chat_query_http.py \
  tests/test_runtime_probes.py \
  tests/test_backend_api_boundaries.py \
  -q
```

Result:

```text
97 passed, 1 warning
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient.
```

This warning comes from the third-party FastAPI/TestClient stack and does not indicate a failing project test.

Focused static check:

```bash
.venv313/bin/python -m pyright -p pyright.venv313.tmp.json
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

The temporary pyright config used only for this local verification pointed pyright at `.venv313`. It was removed after the check so the repository configuration was not changed.

## Environment Notes

- The system default `python3` is Python 3.9.6 and cannot run this project because the code uses Python 3.11+ features such as `enum.StrEnum`.
- The original `.venv` in this workspace contains mixed Python 3.13 and 3.14 paths. For this verification, `.venv313` was created as a clean Python 3.13 environment.
- Future local backend verification should prefer `.venv313/bin/python` unless the project virtual environment is rebuilt cleanly.

## Remaining Work

- Run the full repository pytest suite after the broader version2 implementation settles.
- Run optional live PostgreSQL integration tests in CI with `DATABASE_URL` and `CHATBI_READONLY_DATABASE_URL`.
- Decide whether to standardize the project virtual environment on `.venv313` or rebuild `.venv` cleanly.
- Track the FastAPI/TestClient deprecation warning and update the test client dependency path when the ecosystem migration is ready.
