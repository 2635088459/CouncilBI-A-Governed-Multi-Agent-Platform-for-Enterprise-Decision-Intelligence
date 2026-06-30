# Spec v2: SQL Guardrail and Governance

Source design:
- [Chinese design](../../system_design/04-sql-guardrail-and-governance/VERSION2.zh-CN.md)
- [English design](../../system_design/04-sql-guardrail-and-governance/VERSION2.en.md)

## 1. Purpose
Define the mandatory SQL governance layer that blocks unsafe SQL before database execution and makes every allow/deny decision auditable.

## 2. Scope
In scope:
- SQL AST validation.
- Role/table/field access policy.
- Masking plan generation.
- Row limit and timeout rewrite.
- Audit records for allowed and denied queries.

Out of scope:
- Native database row-level security orchestration.
- Enterprise IAM synchronization.
- Query optimization beyond safety rewrites.

## 3. Typed Inputs and Outputs

### 3.1 GuardrailRequest
Required fields:
- `trace_id: str`
- `user_id: str`
- `role: Literal["business_user", "analyst", "admin"]`
- `sql_text: str` length 1..20000
- `semantic_version_id: str`

### 3.2 GuardrailDecision
Required fields:
- `decision: Literal["allow", "deny"]`
- `rewritten_sql: str | null`
- `sql_hash: str`
- `rule_hits: list[RuleHit]`
- `masking_plan: list[MaskingInstruction]`
- `error: ErrorPayload | null`

## 4. Boundary and Validation Rules
| ID | Rule | Verifier |
|---|---|---|
| VR-04-001 | Non-SELECT statements MUST be denied before database execution. | Negative test |
| VR-04-002 | SQL containing multiple statements MUST be denied. | Negative test |
| VR-04-003 | Runtime database user MUST be read-only; write attempts through that user MUST fail. | Integration test |
| VR-04-004 | Allowed SQL MUST have an enforced row limit <= configured max rows. | Unit test |
| VR-04-005 | Audit events MUST NOT store plaintext database credentials. | Log/audit assertion |

## 5. Functional Requirements
| ID | Requirement |
|---|---|
| FR-04-001 | Guardrail MUST deny `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, and `TRUNCATE`. |
| FR-04-002 | Guardrail MUST deny access to unauthorized tables and fields. |
| FR-04-003 | Guardrail MUST apply masking instructions for fields with masking policies. |
| FR-04-004 | Guardrail MUST rewrite allowed SQL to include a row limit when absent. |
| FR-04-005 | Guardrail MUST write one audit event for every allow or deny decision. |
| FR-04-006 | Denial responses MUST use structured error codes. |

## 6. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-04-001 | Guardrail decision P95 MUST be <= 300ms over 1000 SQL strings in local tests. |
| NFR-04-002 | Known dangerous SQL fixture interception rate MUST be 100%. |
| NFR-04-003 | Audit record write success MUST be 100% in integration tests with PostgreSQL available. |
| NFR-04-004 | Pyright MUST report 0 errors for policy and decision contract types. |

## 7. Acceptance Criteria
| ID | Criterion |
|---|---|
| AC-04-001 | `DROP TABLE orders` returns `decision == "deny"` and error code `SQL_DENIED_WRITE_OPERATION`. |
| AC-04-002 | `SELECT ssn FROM customers` for `business_user` returns `permission_denied` or masked output plan according to policy. |
| AC-04-003 | `SELECT * FROM orders` is rewritten with a configured limit. |
| AC-04-004 | Every decision writes `trace_id`, `sql_hash`, `decision`, `rule_hits`, and latency to audit. |
| AC-04-005 | Runtime database role cannot execute `CREATE TABLE guardrail_probe(id int)`. |

## 8. Test Plan
| ID | Layer | Description |
|---|---|---|
| TC-04-001 | pyright | Validate Guardrail request/decision and policy models. |
| TC-04-002 | pytest negative | Deny dangerous SQL fixture set. |
| TC-04-003 | pytest security | Deny or mask restricted field by role. |
| TC-04-004 | pytest unit | Rewrite missing limit. |
| TC-04-005 | pytest integration | Assert audit row for allow and deny decisions. |
| TC-04-006 | pytest database | Runtime DB user write attempt fails. |
| TC-04-007 | benchmark | Measure Guardrail P95 over 1000 SQL strings. |

## 9. Traceability Matrix
| Requirement | Acceptance Criteria | Test Case |
|---|---|---|
| FR-04-001 | AC-04-001 | TC-04-002 |
| FR-04-002 | AC-04-002 | TC-04-003 |
| FR-04-003 | AC-04-002 | TC-04-003 |
| FR-04-004 | AC-04-003 | TC-04-004 |
| FR-04-005 | AC-04-004 | TC-04-005 |
| FR-04-006 | AC-04-001 | TC-04-002 |
| NFR-04-001 | AC-04-003 | TC-04-007 |
| NFR-04-002 | AC-04-001 | TC-04-002 |
| NFR-04-003 | AC-04-004 | TC-04-005 |
| NFR-04-004 | AC-04-001 | TC-04-001 |

## 10. First Red-Green Steps
1. Define Guardrail request/decision models.
2. Deny one write statement: `DROP TABLE`.
3. Add audit write for denial.
4. Add row-limit rewrite for one SELECT.

