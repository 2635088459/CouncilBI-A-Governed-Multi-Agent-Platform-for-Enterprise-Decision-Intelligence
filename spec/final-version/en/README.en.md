# Final Version Specs — English

Source roadmap: [Final Delivery Roadmap](../../../system_design/final-version/en/09-final-delivery-roadmap.en.md)

These specs define the production-readiness work required for the final industrial submission. Each document is implementation-ready only when every functional requirement maps to at least one acceptance criterion and at least one test case.

## Spec List

| # | Spec | Phase | Status |
|---|---|---|---|
| 01 | [Auth, RBAC, and Tenant Isolation](01-auth-rbac-tenant-isolation.spec.en.md) | Users and permissions | Verified/Implemented |
| 02 | [LLM Provider Gateway](02-llm-provider-gateway.spec.en.md) | Real LLM integration | Draft |
| 03 | [Embedding and Vector RAG](03-embedding-vector-rag.spec.en.md) | Real RAG retrieval | Draft |
| 04 | [Data Platform and Seed Data](04-data-platform-and-seed.spec.en.md) | Data and test corpus | Draft |
| 05 | [Admin Observability](05-admin-observability.spec.en.md) | Admin-only Spec 10 visibility | Draft |
| 06 | [Resilience and Load Testing](06-resilience-and-load-testing.spec.en.md) | Distributed-system readiness | Draft |
| 07 | [Cloud and Kubernetes Deployment](07-cloud-kubernetes-deployment.spec.en.md) | Cloud deployment | Draft |
| 08 | [Final Submission Package](08-final-submission-package.spec.en.md) | Final delivery | Draft |

## SDD + TDD Rules

1. Requirements MUST be numbered and testable.
2. No admin, trace, eval, audit, or release-gate data may be exposed without explicit authorization tests.
3. Real LLM and embedding providers MUST have mock/fake providers for deterministic tests.
4. Tenant isolation MUST be tested for chat history, traces, documents, embeddings, and audit events.
5. Cloud and Kubernetes specs MUST include health checks, secrets, resource limits, and smoke tests.
6. Release readiness MUST include pyright, pytest, security checks, evaluation gates, and human demo acceptance.
