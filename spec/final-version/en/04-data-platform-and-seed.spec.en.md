# Spec FV-04: Data Platform and Seed Data

Source design:
- [Data Platform design](../../../system_design/final-version/en/05-data-platform-and-seed.en.md)
- [Final roadmap](../../../system_design/final-version/en/09-final-delivery-roadmap.en.md)

## 1. Purpose
Define migrations, repeatable seed datasets, data quality checks, and test data volumes required to validate the final platform.

## 2. Scope
In scope:
- Application, business, knowledge, and runtime data domains.
- Schema migrations, seed profiles, data quality checks, and CI/local commands.
- Small, medium, and large datasets for tests, integration, and load testing.

Out of scope:
- Production customer data ingestion.
- Vendor-specific data warehouse replacement.

## 3. Functional Requirements
| ID | Requirement |
|---|---|
| FR-FV04-001 | Schema changes MUST be represented as migrations. |
| FR-FV04-002 | Seed profiles MUST include `small`, `medium`, and `large`. |
| FR-FV04-003 | Small seed MUST support CI and unit/integration tests. |
| FR-FV04-004 | Medium seed MUST support local end-to-end demo and integration tests. |
| FR-FV04-005 | Large seed MUST support load and performance testing. |
| FR-FV04-006 | Seed data MUST include at least two tenants for isolation tests. |
| FR-FV04-007 | Business records and documents MUST share scenarios that support evidence-backed answers. |
| FR-FV04-008 | Seed commands MUST be repeatable and idempotent or safely resettable. |

## 4. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-FV04-001 | Small seed SHOULD complete <= 30s locally. |
| NFR-FV04-002 | Seed generation MUST not require real LLM or embedding APIs in CI. |
| NFR-FV04-003 | Quality checks MUST fail fast when required tables or vectors are empty. |
| NFR-FV04-004 | Large seed MUST be optional and never run by default in CI. |

## 5. Seed Profiles
| Profile | Purpose | Minimum Content |
|---|---|---|
| small | CI and smoke tests | 2 orgs, 5 users, hundreds of business rows, document chunks |
| medium | local demo | 5 orgs, dozens of users, 100k business rows, thousands of chunks |
| large | load testing | multi-org, million-scale business rows, large trace/query history |

## 6. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-FV04-001 | One command can rebuild local small demo data. |
| AC-FV04-002 | CI can run small seed and quality checks. |
| AC-FV04-003 | Medium seed supports an end-to-end ChatBI query with document evidence. |
| AC-FV04-004 | Large seed can be generated explicitly for load testing. |
| AC-FV04-005 | Quality checks validate foreign keys, metric sanity, vector counts, and tenant separation. |

## 7. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-FV04-001 | migration | Apply migrations from empty database. |
| TC-FV04-002 | seed | Run small seed twice using reset/idempotent mode. |
| TC-FV04-003 | quality | Validate required tables, tenant counts, and foreign keys. |
| TC-FV04-004 | quality | Validate chunk count equals vector count in seeded vector store. |
| TC-FV04-005 | integration | Run a seeded business question and retrieve matching document evidence. |
| TC-FV04-006 | negative | Tenant leakage quality check fails on intentionally mixed records. |
| TC-FV04-007 | load-prep | Large seed command is explicit and not part of default CI. |

## 8. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-FV04-001 | AC-FV04-001 | TC-FV04-001 |
| FR-FV04-002 | AC-FV04-004 | TC-FV04-002, TC-FV04-007 |
| FR-FV04-003 | AC-FV04-002 | TC-FV04-002 |
| FR-FV04-004 | AC-FV04-003 | TC-FV04-005 |
| FR-FV04-005 | AC-FV04-004 | TC-FV04-007 |
| FR-FV04-006 | AC-FV04-005 | TC-FV04-003, TC-FV04-006 |
| FR-FV04-007 | AC-FV04-003 | TC-FV04-005 |
| FR-FV04-008 | AC-FV04-001 | TC-FV04-002 |

