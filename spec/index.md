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

Before implementation, review each spec against [Spec Review Gate](version1/spec-review-gate.md). A requirement is not implementation-ready until it maps to a type constraint, test case, benchmark, or compliance assertion.

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

## Requirement ID Convention

```
FR-XX-NNN   Functional Requirement  (e.g. FR-01-001 = spec 01, requirement 1)
NFR-XX-NNN  Non-functional Requirement
AC-XX-NNN   Acceptance Criterion
TC-XX-NNN   Test Case
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
