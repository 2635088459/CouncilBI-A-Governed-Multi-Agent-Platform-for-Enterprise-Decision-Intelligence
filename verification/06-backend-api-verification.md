# Verification: 06 Backend API

This document records the machine-verifiable status for `spec/version1/06-backend-api.spec.md`.

## Scope

Verified workflow:

```text
FastAPI HTTP request
  -> header/auth/trace validation
  -> ChatBIApplication
  -> SimpleOrchestrator
  -> unified ApiEnvelope
  -> audit record
```

Covered API surface:

| Endpoint | Status |
|---|---|
| `POST /api/v1/chat/query` | Implemented |
| `GET /api/v1/chat/history` | Implemented with cursor pagination |
| `GET /api/v1/query/{trace_id}` | Implemented from in-memory history |
| `GET /api/v1/metrics/catalog` | Implemented from data model catalog |
| `GET /api/v1/datasets/catalog` | Implemented from data model catalog |
| `GET /api/v1/audit/{trace_id}` | Implemented from in-memory API audit records |
| `POST /api/v1/evals/run` | Implemented as an in-process benchmark smoke run |
| `GET /api/v1/health` | Implemented as authenticated unified-envelope health check |

Covered requirements:

| Requirement | Verification |
|---|---|
| `FR-06-001` | `tests/test_http_app.py::test_chat_query_endpoint_returns_success_envelope` |
| `FR-06-002` | `tests/test_http_app.py::test_chat_history_endpoint_returns_paginated_items` |
| `FR-06-003` | `tests/test_http_app.py::test_query_detail_endpoint_returns_trace_record` |
| `FR-06-004` | `tests/test_http_app.py::test_metrics_catalog_endpoint_returns_metric_definitions` |
| Catalog design | `tests/test_http_app.py::test_datasets_catalog_endpoint_returns_table_and_column_metadata` |
| `FR-06-005` | `tests/test_http_app.py::test_chat_query_without_authorization_returns_auth_error_envelope` |
| `FR-06-006` | `tests/test_http_app.py::test_chat_query_idempotency_key_returns_same_response` |
| `FR-06-007` | `tests/test_http_app.py::test_audit_endpoint_returns_records_for_trace_id` |
| Evaluation API design | `tests/test_http_app.py::test_eval_run_endpoint_returns_quality_report` |
| Health/config API design | `tests/test_http_app.py::test_health_endpoint_returns_unified_envelope` |
| `NFR-06-003` | `tests/test_api_models.py`, `tests/test_http_app.py::test_core_endpoints_use_unified_envelope_shape` |
| `NFR-06-004` | `tests/test_app.py::test_handle_chat_query_enforces_user_rate_limit` |

## Design Notes

The Backend API slice keeps three layers separate:

1. `src/chatbi/api/models.py` defines public request and response contracts.
2. `src/chatbi/api/http.py` handles FastAPI routing, headers, HTTP status codes, and validation errors.
3. `src/chatbi/application/app.py` owns application behavior such as idempotency, pagination, catalog lookup, rate limiting, and audit records.

In plain terms: `http.py` is the front desk, `app.py` is the service desk, and the orchestrator/agents are the teachers doing the actual analysis work.

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Static check:

```bash
.venv/bin/python -m pyright
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Test suite:

```bash
.venv/bin/python -m pytest
```

Result:

```text
187 passed, 1 warning
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient
```

This warning comes from the third-party FastAPI/TestClient stack and does not indicate a failing project test.
