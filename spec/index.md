# Spec Master Index — Governed Multi-Agent ChatBI Platform

This index covers all versioned system-level specs, each derived from the system design documents.
Every spec follows SDD + TDD: scope → numbered requirements → contracts → acceptance criteria → test plan → traceability matrix.

---

## How to Read a Spec

| Section | SDD or TDD | Purpose |
|---|---|---|
| Purpose / Scope | SDD | What this module is and what it is not |
| Actors | SDD | Who interacts with this module |
| Functional / Non-functional Requirements | SDD | Numbered, testable constraints |
| Architecture Decisions | SDD | Key design choices and rationale |
| Contracts | SDD | Input/output schemas and APIs |
| Acceptance Criteria | TDD | Pass/fail conditions for the whole module |
| Test Plan | TDD | Unit, integration, E2E, negative tests |
| Traceability Matrix | SDD+TDD | FR → AC → TC linkage |
| Open Questions | Both | Pending decisions that affect design or tests |

Before implementation, review each spec against [Spec Review Gate](version1/spec-review-gate.md). A requirement is not implementation-ready until it maps to a type constraint, test case, benchmark, or compliance assertion. For v2 implementation, use the v2 specs below as the current source of truth.

For final industrial submission, use the final-version specs as the production-readiness source of truth:

- English: [final-version/en/README.en.md](final-version/en/README.en.md)
- Chinese: [final-version/zh-CN/README.zh-CN.md](final-version/zh-CN/README.zh-CN.md)

---

## Version 1 Spec Index

| # | File | System Part | Status |
|---|---|---|---|
| 01 | [01-overall-architecture.spec.md](version1/01-overall-architecture.spec.md) | Overall Architecture | Draft |
| 02 | [02-agent-orchestration.spec.md](version1/02-agent-orchestration.spec.md) | Agent Orchestration | Draft |
| 03 | [03-semantic-layer-and-nl2sql.spec.md](version1/03-semantic-layer-and-nl2sql.spec.md) | Semantic Layer + NL2SQL | Draft |
| 04 | [04-sql-guardrail-and-governance.spec.md](version1/04-sql-guardrail-and-governance.spec.md) | SQL Guardrail + Governance | Draft |
| 05 | [05-data-model.spec.md](version1/05-data-model.spec.md) | Data Model | Draft |
| 06 | [06-backend-api.spec.md](version1/06-backend-api.spec.md) | Backend API | Draft |
| 07 | [07-frontend-chatbi.spec.md](version1/07-frontend-chatbi.spec.md) | Frontend ChatBI | Draft |
| 08 | [08-rag.spec.md](version1/08-rag.spec.md) | RAG Retrieval + Evidence | Draft |
| 09 | [09-analytics-and-forecasting.spec.md](version1/09-analytics-and-forecasting.spec.md) | Analytics + Forecasting | Draft |
| 10 | [10-evaluation-and-observability.spec.md](version1/10-evaluation-and-observability.spec.md) | Evaluation + Observability | Draft |

---

## Version 2 Spec Index

| # | File | System Part | Status |
|---|---|---|---|
| 01 | [01-overall-architecture.spec.md](version2/01-overall-architecture.spec.md) | Overall Architecture | Verifiable Draft |
| 02 | [02-agent-orchestration.spec.md](version2/02-agent-orchestration.spec.md) | Agent Orchestration | Verifiable Draft |
| 03 | [03-semantic-layer-and-nl2sql.spec.md](version2/03-semantic-layer-and-nl2sql.spec.md) | Semantic Layer + NL2SQL | Verifiable Draft |
| 04 | [04-sql-guardrail-and-governance.spec.md](version2/04-sql-guardrail-and-governance.spec.md) | SQL Guardrail + Governance | Verifiable Draft |
| 05 | [05-data-model.spec.md](version2/05-data-model.spec.md) | Data Model | Verifiable Draft |
| 06 | [06-backend-api.spec.md](version2/06-backend-api.spec.md) | Backend API | Verifiable Draft |
| 07 | [07-frontend-chatbi.spec.md](version2/07-frontend-chatbi.spec.md) | Frontend ChatBI | Verifiable Draft |
| 08 | [08-rag.spec.md](version2/08-rag.spec.md) | RAG Retrieval + Evidence | Verifiable Draft |
| 09 | [09-analytics-and-forecasting.spec.md](version2/09-analytics-and-forecasting.spec.md) | Analytics + Forecasting | Verifiable Draft |
| 10 | [10-evaluation-and-observability.spec.md](version2/10-evaluation-and-observability.spec.md) | Evaluation + Observability | Verifiable Draft |

---

## Final Version Spec Index

| # | English | 中文 | System Part | Status |
|---|---|---|---|---|
| 01 | [Auth, RBAC, and Tenant Isolation](final-version/en/01-auth-rbac-tenant-isolation.spec.en.md) | [Auth、RBAC 与多租户隔离](final-version/zh-CN/01-auth-rbac-tenant-isolation.spec.zh-CN.md) | Users and permissions | Verified/Implemented |
| 02 | [LLM Provider Gateway](final-version/en/02-llm-provider-gateway.spec.en.md) | [LLM Provider Gateway](final-version/zh-CN/02-llm-provider-gateway.spec.zh-CN.md) | Real LLM integration | Draft |
| 03 | [Embedding and Vector RAG](final-version/en/03-embedding-vector-rag.spec.en.md) | [Embedding 与 Vector RAG](final-version/zh-CN/03-embedding-vector-rag.spec.zh-CN.md) | Real RAG retrieval | Draft |
| 04 | [Data Platform and Seed Data](final-version/en/04-data-platform-and-seed.spec.en.md) | [数据平台与 Seed 数据](final-version/zh-CN/04-data-platform-and-seed.spec.zh-CN.md) | Data and test corpus | Draft |
| 05 | [Admin Observability](final-version/en/05-admin-observability.spec.en.md) | [Admin 可观测性](final-version/zh-CN/05-admin-observability.spec.zh-CN.md) | Admin-only Spec 10 visibility | Draft |
| 06 | [Resilience and Load Testing](final-version/en/06-resilience-and-load-testing.spec.en.md) | [韧性与压测](final-version/zh-CN/06-resilience-and-load-testing.spec.zh-CN.md) | Distributed-system readiness | Draft |
| 07 | [Cloud and Kubernetes Deployment](final-version/en/07-cloud-kubernetes-deployment.spec.en.md) | [云端与 Kubernetes 部署](final-version/zh-CN/07-cloud-kubernetes-deployment.spec.zh-CN.md) | Cloud deployment | Draft |
| 08 | [Final Submission Package](final-version/en/08-final-submission-package.spec.en.md) | [最终提交包](final-version/zh-CN/08-final-submission-package.spec.zh-CN.md) | Final delivery | Draft |

---

## Requirement ID Convention

```
FR-XX-NNN   Functional Requirement  (e.g. FR-01-001 = spec 01, requirement 1)
NFR-XX-NNN  Non-functional Requirement
AC-XX-NNN   Acceptance Criterion
TC-XX-NNN   Test Case
FR-FVXX-NNN Final-version Functional Requirement (e.g. FR-FV01-001)
```

---

## Cross-Spec Dependencies

```
01 (Architecture) ──► 02 (Orchestration) ──► 03 (NL2SQL)
                                          ──► 04 (Guardrail)
                  ──► 06 (API)            ──► 07 (Frontend)
                  ──► 05 (Data Model)     ──► 08 (RAG)
                                          ──► 09 (Analytics)
                  ──► 10 (Evaluation)
```

---

## Links to System Design

Full design documents live in [../system_design/system-design-index.en.md](../system_design/system-design-index.en.md).
