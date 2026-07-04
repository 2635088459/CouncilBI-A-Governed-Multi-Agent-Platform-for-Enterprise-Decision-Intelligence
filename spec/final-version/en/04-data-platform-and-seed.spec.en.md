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
| FR-FV04-009 | Seed generation MUST produce deterministic business rows and vector RAG documents that share the same demo scenarios. |
| FR-FV04-010 | A local seed command MUST run small seed and quality checks without real provider APIs. |
| FR-FV04-011 | Seed commands MUST be able to export a deterministic local JSON artifact for review and downstream import. |
| FR-FV04-012 | Exported seed artifacts MUST be independently readable and quality-checkable without regenerating the seed dataset. |
| FR-FV04-013 | Local Docker demo seed MUST include a deterministic 2012 monthly revenue slice so aggregation questions such as highest-month queries can be answered from data, not hardcoded UI text. |
| FR-FV04-014 | SQL-backed demo answers that use seeded business rows SHOULD expose data-provenance evidence when document RAG is not part of the route. |
| FR-FV04-015 | Local Docker demo seed MUST include at least one non-revenue enterprise read model for support-ticket operations. |
| FR-FV04-016 | Seeded business rows and knowledge documents MUST include a shared support-ticket scenario so answer synthesis can combine table data and document evidence. |

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
| AC-FV04-006 | Seeded vector RAG evidence can answer the seeded campaign/revenue scenario. |
| AC-FV04-007 | Running the small seed artifact export twice produces byte-identical JSON content. |
| AC-FV04-008 | An exported seed artifact can be reloaded and quality checked from disk, and corrupted counts or tenant links fail validation. |
| AC-FV04-009 | A local Docker query for `Which month had the highest revenue in 2012?` returns 2012 rows, identifies the highest month, and includes data-provenance evidence. |
| AC-FV04-010 | A local Docker query about support tickets returns support-ticket rows, includes support-operations evidence, and does not use the revenue read model. |

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
| TC-FV04-008 | command | `chatbi-seed-final --profile small` builds small seed and passes quality checks. |
| TC-FV04-009 | unit | Final seed profiles expose deterministic small, medium, and explicit-only large profiles. |
| TC-FV04-010 | command | `chatbi-seed-final --profile small --output-json <path>` writes deterministic artifact JSON. |
| TC-FV04-011 | command | `chatbi-seed-final --validate-json <path>` reloads an exported artifact and runs quality checks. |
| TC-FV04-012 | integration | 2012 highest-revenue query returns `2012-12`, 12 monthly rows, and a provenance evidence item. |
| TC-FV04-012 | negative | Artifact validation fails on vector count mismatch or tenant leakage inside the JSON payload. |
| TC-FV04-013 | migration | Base migration creates and seeds `business.support_ticket_summary`. |
| TC-FV04-014 | integration | Support-ticket question returns non-revenue rows and document/data evidence. |

Implemented test coverage:
- `tests/test_final_seed.py`

Implemented source module:
- `src/chatbi/final_seed.py`

Implemented local command:
- `chatbi-seed-final --profile small`
- `chatbi-seed-final --profile small --output-json /tmp/chatbi-small-seed.json`
- `chatbi-seed-final --validate-json /tmp/chatbi-small-seed.json`

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
| FR-FV04-009 | AC-FV04-003, AC-FV04-006 | TC-FV04-005 |
| FR-FV04-010 | AC-FV04-001, AC-FV04-002 | TC-FV04-008 |
| FR-FV04-011 | AC-FV04-007 | TC-FV04-010 |
| FR-FV04-012 | AC-FV04-008 | TC-FV04-011, TC-FV04-012 |
| FR-FV04-013 | AC-FV04-009 | TC-FV04-012 |
| FR-FV04-014 | AC-FV04-009 | TC-FV04-012 |
| FR-FV04-015 | AC-FV04-010 | TC-FV04-013, TC-FV04-014 |
| FR-FV04-016 | AC-FV04-010 | TC-FV04-014 |
| NFR-FV04-002 | AC-FV04-002 | TC-FV04-002, TC-FV04-008 |
| NFR-FV04-004 | AC-FV04-004 | TC-FV04-007 |
