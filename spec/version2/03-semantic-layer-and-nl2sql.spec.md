# Spec v2: Semantic Layer and NL2SQL

Source design:
- [Chinese design](../../system_design/03-semantic-layer-and-nl2sql/VERSION2.zh-CN.md)
- [English design](../../system_design/03-semantic-layer-and-nl2sql/VERSION2.en.md)

## 1. Purpose
Define a database-backed semantic layer and a verifiable NL2SQL pipeline. The spec prevents implementation from guessing fields, bypassing permissions, or generating SQL without a semantic version.

## 2. Scope
In scope:
- PostgreSQL semantic catalog tables.
- Metric and dimension resolution.
- SQL preview and SQL generation contracts.
- Semantic versioning, schema snapshot, and frontend catalog APIs.

Out of scope:
- Automatic enterprise-wide lineage discovery.
- Arbitrary cross-database federation.
- Training or fine-tuning an LLM for SQL generation.

## 3. Typed Inputs and Outputs

### 3.1 SemanticResolveRequest
Required fields:
- `trace_id: str`
- `user_id: str`
- `role: Literal["business_user", "analyst", "admin"]`
- `question: str` length 1..2000
- `locale: Literal["en", "zh-CN"]`

### 3.2 SemanticResolveResponse
Required fields:
- `semantic_version_id: str`
- `metrics: list[MetricRef]`
- `dimensions: list[DimensionRef]`
- `time_range: TimeRange | null`
- `filters: list[FilterRef]`
- `status: Literal["resolved", "needs_clarification", "permission_denied"]`
- `clarification_question: str | null`

### 3.3 SqlPreviewResponse
Required fields:
- `sql_text: str`
- `sql_hash: str`
- `explanation: str`
- `semantic_version_id: str`
- `executes: Literal[false]`

## 4. Boundary and Validation Rules
| ID | Rule | Verifier |
|---|---|---|
| VR-03-001 | SQL generation MUST use only metric and dimension ids resolved from active semantic catalog rows. | Unit test |
| VR-03-002 | If a metric is ambiguous, response status MUST be `needs_clarification`; SQL MUST NOT be generated. | Negative test |
| VR-03-003 | Unauthorized metrics or dimensions MUST return `permission_denied`; SQL MUST NOT be generated. | Security test |
| VR-03-004 | `POST /api/v1/sql/preview` MUST NOT execute SQL. | Integration test with mock executor call count |
| VR-03-005 | Every generated SQL preview MUST include `semantic_version_id`. | Contract test |

## 5. Functional Requirements
| ID | Requirement |
|---|---|
| FR-03-001 | The system MUST load metric catalog entries from PostgreSQL. |
| FR-03-002 | The system MUST expose `GET /api/v1/metrics/catalog`. |
| FR-03-003 | The resolver MUST map benchmark questions to canonical metric ids and dimension ids. |
| FR-03-004 | SQL generation MUST include only authorized tables and fields. |
| FR-03-005 | Schema drift detection MUST compare current schema snapshot to the previous snapshot and emit changed fields. |
| FR-03-006 | New metrics MUST be reproducible through migration or seed data. |

## 6. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-03-001 | Catalog API with 100 metrics and 200 dimensions MUST respond P95 <= 200ms locally with PostgreSQL. |
| NFR-03-002 | Resolver MUST be deterministic: the same benchmark input repeated 20 times returns identical metric and dimension ids. |
| NFR-03-003 | Pyright MUST report 0 errors for semantic catalog and SQL preview contract types. |

## 7. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-03-001 | Catalog API returns seeded metric `revenue` with id, formula, owner, status, and semantic version. |
| AC-03-002 | Question "show monthly revenue for 2024" resolves to metric `revenue` and grain `month`. |
| AC-03-003 | An unauthorized role requesting a restricted metric receives `permission_denied` and no SQL. |
| AC-03-004 | Ambiguous metric phrase returns one clarification question and no SQL. |
| AC-03-005 | SQL preview returns `executes == false` and executor call count remains 0. |

## 8. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-03-001 | pyright | Validate semantic request/response and catalog models. |
| TC-03-002 | pytest database | Load seed catalog and fetch `revenue`. |
| TC-03-003 | pytest resolver | Resolve fixed benchmark question to expected ids. |
| TC-03-004 | pytest security | Restricted metric returns permission denial. |
| TC-03-005 | pytest negative | Ambiguous question returns clarification and no SQL. |
| TC-03-006 | pytest integration | SQL preview does not call executor. |
| TC-03-007 | benchmark | Measure catalog API P95 over 100 metrics and 200 dimensions. |
| TC-03-008 | determinism | Repeat same benchmark input 20 times and compare canonical ids. |

## 9. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-03-001 | AC-03-001 | TC-03-002 |
| FR-03-002 | AC-03-001 | TC-03-002 |
| FR-03-003 | AC-03-002 | TC-03-003 |
| FR-03-004 | AC-03-003 | TC-03-004 |
| FR-03-005 | AC-03-001 | TC-03-002 |
| FR-03-006 | AC-03-001 | TC-03-002 |
| NFR-03-001 | AC-03-001 | TC-03-007 |
| NFR-03-002 | AC-03-002 | TC-03-008 |
| NFR-03-003 | AC-03-001 | TC-03-001 |

## 10. First Red-Green Steps
1. Create typed catalog models.
2. Add seed metric `revenue` and catalog read test.
3. Implement resolver for one benchmark question.
4. Add permission denial before SQL preview.

