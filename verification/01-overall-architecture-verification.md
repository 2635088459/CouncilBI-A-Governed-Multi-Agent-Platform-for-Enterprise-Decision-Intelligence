# Verification: 01 Overall Architecture

This document records the current machine-verifiable status for the minimal implementation slice based on `spec/version1/01-overall-architecture.spec.md`.

## Scope

Verified workflow:

```text
ChatQueryRequestPayload
  -> ChatBIApplication
  -> SimpleOrchestrator
  -> SimpleSqlGuardrail
  -> InMemoryQueryHistory
  -> ApiEnvelope
```

Covered requirements:

| Requirement | Verification |
|---|---|
| `FR-01-001` | `tests/test_app.py`, `tests/test_simple_orchestrator.py` |
| `FR-01-002` | `tests/test_overall_architecture.py`, `tests/test_api_models.py` |
| `FR-01-003` | `tests/test_simple_orchestrator.py`, `tests/test_app.py` |
| `FR-01-004` | `tests/test_simple_guardrail.py`, `tests/test_simple_orchestrator.py` |
| `FR-01-005` | `tests/test_in_memory_history.py`, `tests/test_app.py` |
| `FR-01-008` | `tests/test_in_memory_history.py`, `tests/test_simple_orchestrator.py` |
| `AC-01-001` | `tests/test_app.py`, `tests/test_http_app.py` |
| `AC-01-002` | `tests/test_simple_guardrail.py`, `tests/test_http_app.py` |
| `AC-01-003` | `tests/test_in_memory_history.py`, `tests/test_simple_orchestrator.py` |
| `AC-01-004` | `tests/test_in_memory_history.py`, `tests/test_app.py` |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Layer 1 static check:

```bash
.venv/bin/python -m pyright
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Layer 2 test suite:

```bash
.venv/bin/python -m pytest
```

Result:

```text
36 passed, 1 warning
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient
```

This warning comes from the third-party FastAPI/TestClient stack and does not indicate a failing project test.

## Docker Decision

Docker is not required for this slice because the current implementation only uses in-process Python components and an in-memory history store.

Use Docker when the project introduces external runtime dependencies such as:

- PostgreSQL or MySQL
- Redis
- pgvector or Qdrant
- integration tests that require multiple services
- a reproducible demo environment for graders or teammates
