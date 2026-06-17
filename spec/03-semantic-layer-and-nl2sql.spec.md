# Spec: Semantic Layer and NL2SQL

## 1. Purpose
Define the governed semantic model and the path from natural-language questions to safe, explainable SQL.

## 2. Scope
In scope:
- Metric catalog, dimension catalog, join paths
- NL parsing and entity resolution
- SQL planning, generation, and explanation
- Semantic versioning

Out of scope:
- Full enterprise lineage platform
- Multilingual semantic catalog beyond CN/EN in v1

Assumptions:
- Metric definitions are the single source of truth.
- All SQL generation passes through the semantic layer before guardrail.

Constraints:
- SQL generation MUST NOT bypass semantic object resolution.
- Every SQL candidate MUST carry semantic_version.

## 3. Core Model
- metric, dimension, time_grain, filter_template, join_path

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-03-001 | The semantic layer MUST maintain a canonical definition for each metric. |
| FR-03-002 | Business synonyms MUST resolve to canonical metric names before SQL generation. |
| FR-03-003 | The parser MUST extract metric, dimension, time range, and intent from any question. |
| FR-03-004 | Every generated SQL MUST include an explanation covering metric, filters, and aggregation. |
| FR-03-005 | When multiple metric definitions match a term, the system MUST trigger a clarification. |
| FR-03-006 | Missing time context MUST default to last 30 days unless policy overrides. |
| FR-03-007 | Generated SQL MUST be passed to the Guardrail before execution. |
| FR-03-008 | Each SQL output MUST record the semantic_version it was built with. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-03-001 | SQL accuracy MUST be >= 90% on the benchmark question set. |
| NFR-03-002 | Semantic entity resolution MUST be stable for the same question input. |
| NFR-03-003 | High-sensitivity fields MUST be blocked from query generation by policy. |
| NFR-03-004 | Metric definition changes MUST increment semantic_version. |

## 6. Workflow
1. Parse NL question into intent, metrics, dimensions, time.
2. Resolve synonyms to canonical entities.
3. Build query plan (table, joins, filters, aggregation).
4. Generate SQL via template rules.
5. Generate SQL explanation.
6. Hand off to Guardrail.

## 7. Contracts

Input:
```
question, locale, user_role, context_window, semantic_version
```

Output:
```
intent_type, resolved_metrics, resolved_dimensions,
time_range, generated_sql, sql_explanation, confidence, warnings
```

## 8. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-03-001 | "revenue" and "sales amount" resolve to the same canonical metric. |
| AC-03-002 | A question without a time expression defaults to last 30 days in SQL. |
| AC-03-003 | Two different metric definitions for the same term triggers a clarification response. |
| AC-03-004 | Every SQL output is accompanied by an sql_explanation field. |
| AC-03-005 | A high-sensitivity field query returns a denial rather than SQL. |
| AC-03-006 | Metric definition change increments semantic_version in the output. |

## 9. Test Plan

| ID | Type | Description |
|---|---|---|
| TC-03-001 | Unit | Synonym dictionary maps all known aliases to canonical metrics. |
| TC-03-002 | Unit | Time expression parser returns expected date range for "last month". |
| TC-03-003 | Unit | SQL template produces correct aggregation for revenue definition. |
| TC-03-004 | Integration | NL question → SQL → Guardrail handoff succeeds. |
| TC-03-005 | Negative | Ambiguous metric term returns clarification prompt, not SQL. |
| TC-03-006 | Negative | High-sensitivity field returns policy denial message. |

## 10. Traceability Matrix

| Requirement | Acceptance Criterion | Test Case |
|---|---|---|
| FR-03-002 | AC-03-001 | TC-03-001 |
| FR-03-003 | AC-03-002 | TC-03-002 |
| FR-03-004 | AC-03-004 | TC-03-003 |
| FR-03-005 | AC-03-003 | TC-03-005 |
| FR-03-007 | AC-03-004 | TC-03-004 |
| NFR-03-003 | AC-03-005 | TC-03-006 |
| NFR-03-004 | AC-03-006 | TC-03-002 |

## 11. Open Questions
- OQ-03-001: DSL intermediate layer before SQL templates?
- OQ-03-002: User-defined draft metrics with approval workflow?
- OQ-03-003: Few-shot SQL correction chain in v1?
