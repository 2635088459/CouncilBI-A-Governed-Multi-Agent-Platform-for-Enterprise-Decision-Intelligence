# API Documentation

This document summarizes the implemented API surfaces used by the final demo
and verification package.

## Auth

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/auth/signup` | POST | Create organization user credentials. |
| `/api/v2/auth/login` | POST | Exchange credentials for access and refresh tokens. |
| `/api/v2/auth/refresh` | POST | Refresh an access token. |
| `/api/v2/me` | GET | Return authenticated user, organization, roles, and permissions. |

Auth-protected v2 endpoints require `Authorization: Bearer <token>`.

## Chat

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/chat/query` | POST | Legacy ChatBI query endpoint. |
| `/api/v2/chat/query` | POST | Authenticated tenant-aware ChatBI query endpoint. |
| `/api/v1/query/{trace_id}` | GET | Read query replay/detail by trace id. |
| `/api/v2/chat/tasks/{task_id}` | GET | Read async task status. |

## RAG And Documents

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/documents/index` | POST | Queue or execute document indexing for RAG. |
| `/api/v2/documents/index` | POST | Authenticated tenant-aware document indexing. |

RAG answers include citations/evidence when matching chunks are retrieved.

## Admin

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v2/admin/observability/summary` | GET | Admin-only health, LLM, SQL safety, RAG, eval, release gate, and audit summary. |
| `/api/v1/quality/dashboard` | GET | Legacy quality dashboard payload. |

## Evaluation

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/evals/run` | POST | Run an evaluation suite. |
| `/api/v1/evals/{eval_run_id}` | GET | Read saved evaluation report. |
| `/api/v2/evals/run` | POST | Authenticated admin evaluation run. |
| `/api/v2/evals/{eval_run_id}` | GET | Authenticated admin evaluation report. |

## Observability

| Endpoint | Method | Purpose |
|---|---|---|
| `/healthz` | GET | Liveness probe. |
| `/readyz` | GET | Readiness probe. |
| `/metrics` | GET | Runtime metrics text. |
| `/api/v1/observability/traces/{trace_id}` | GET | Trace, audit, logs, and final answer inspection. |
| `/api/v2/governance/traces/{trace_id}` | GET | Authenticated governance trace summary. |
