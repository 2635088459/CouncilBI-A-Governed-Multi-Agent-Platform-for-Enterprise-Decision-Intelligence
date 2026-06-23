# Spec: SQL Guardrail and Governance

## 1. Purpose
Define the policy engine that ensures only safe, authorized SQL reaches the database and that every decision is auditable.

## 2. Scope
In scope:
- SELECT-only enforcement
- AST validation
- Row limit and timeout injection
- Table and column authorization
- Audit logging and replay

Out of scope:
- Native DB row-level security orchestration
- Enterprise IAM federation

Assumptions:
- All SQL passes through the Guardrail before execution.
- Deny overrides allow at every policy level.

Constraints:
- Zero tolerance for passing high-risk SQL.
- Every decision MUST write an audit record.

## 3. Policy Levels
- L1: statement-level (SELECT only)
- L2: structural-level (multi-statement, comment-escape)
- L3: object-level (table/column ACL)
- L4: function-level (risky functions)
- L5: runtime-level (limit, timeout, rate)

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-04-001 | The Guardrail MUST reject any SQL that is not a single SELECT statement. |
| FR-04-002 | The Guardrail MUST reject DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE. |
| FR-04-003 | The Guardrail MUST inject a row LIMIT before execution if absent. |
| FR-04-004 | The Guardrail MUST cancel any query that exceeds the configured timeout. |
| FR-04-005 | The Guardrail MUST deny access to tables or columns not permitted for the user role. |
| FR-04-006 | The Guardrail MUST mask PII fields before returning results. |
| FR-04-007 | On any denial, the Guardrail MUST return a structured error code and safe message. |
| FR-04-008 | Every Guardrail decision MUST be written to the audit log with full context. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-04-001 | Guardrail check latency P95 MUST be <= 300ms. |
| NFR-04-002 | Dangerous SQL interception rate MUST be >= 99.5%. |
| NFR-04-003 | False-positive block rate on valid SQL MUST be <= 1%. |
| NFR-04-004 | Audit log completeness MUST be 100% — no decision may be unlogged. |

## 6. Workflow
1. Normalize SQL text.
2. Build AST.
3. Run L1 → L5 checks in order.
4. Inject LIMIT and timeout on allow.
5. Execute or deny.
6. Write audit record.

## 7. Contracts

Input:
```
sql_text, user_id, user_role, tenant_id, trace_id
```

Output:
```
decision (allow|deny), safe_sql, policy_hits, risk_level, message, trace_id
```

Error codes:
```
SQL_DENY_STATEMENT, SQL_DENY_OBJECT, SQL_DENY_FUNCTION,
SQL_DENY_TIMEOUT, SQL_DENY_RATE_LIMIT
```

## 8. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-04-001 | DROP TABLE is rejected with code SQL_DENY_STATEMENT. |
| AC-04-002 | SELECT without LIMIT gets auto-injected LIMIT before execution. |
| AC-04-003 | A query exceeding timeout is cancelled and returns SQL_DENY_TIMEOUT. |
| AC-04-004 | A business_user cannot query a restricted table; returns SQL_DENY_OBJECT. |
| AC-04-005 | PII field value is masked in query results. |
| AC-04-006 | Every decision (allow and deny) has a complete audit record. |
| AC-04-007 | A replayed trace_id returns the same original SQL and decision. |

## 9. Test Plan

| ID | Type | Description |
|---|---|---|
| TC-04-001 | Unit | AST parser correctly identifies SELECT vs non-SELECT. |
| TC-04-002 | Unit | LIMIT injector adds correct row limit when absent. |
| TC-04-003 | Negative | 20 SQL injection variants are all blocked. |
| TC-04-004 | Negative | Role business_user blocked from restricted tables. |
| TC-04-005 | Negative | Query exceeding timeout returns SQL_DENY_TIMEOUT. |
| TC-04-006 | Integration | Allow path: valid SQL reaches DB and result is returned. |
| TC-04-007 | Integration | Audit record exists for every TC-04-001 through TC-04-006 run. |

## 10. Traceability Matrix

| Requirement | Acceptance Criterion | Test Case |
|---|---|---|
| FR-04-001 | AC-04-001 | TC-04-001, TC-04-003 |
| FR-04-003 | AC-04-002 | TC-04-002 |
| FR-04-004 | AC-04-003 | TC-04-005 |
| FR-04-005 | AC-04-004 | TC-04-004 |
| FR-04-006 | AC-04-005 | TC-04-006 |
| FR-04-008 | AC-04-006, AC-04-007 | TC-04-007 |
| NFR-04-002 | AC-04-001 | TC-04-003 |
| NFR-04-004 | AC-04-006 | TC-04-007 |

## 11. Open Questions
- OQ-04-001: DB proxy layer for second-stage validation?
- OQ-04-002: Externalize authorization policy to OPA?
- OQ-04-003: Human approval workflow for exceptional access?
