# Verification: 03 Semantic Layer and NL2SQL

This document records the current machine-verifiable status for the first implementation slice based on `spec/version1/03-semantic-layer-and-nl2sql.spec.md`.

## Scope

Verified workflow:

```text
business term
  -> SemanticCatalog
  -> canonical MetricDefinition
  -> semantic_version

question
  -> QuestionParser
  -> resolved metric
  -> explicit or default last-30-days TimeRange

parsed question
  -> SqlTemplateGenerator
  -> generated SQL
  -> sql_explanation
  -> semantic_version

generated SQL
  -> SemanticNl2SqlPipeline
  -> SimpleSqlGuardrail
  -> allow/deny GuardrailResult

ambiguous business term
  -> multiple MetricDefinition candidates
  -> clarification message
  -> no SQL generated
```

This slice verifies canonical metric definitions, synonym resolution, metric extraction, default time-range parsing, template SQL generation, guardrail handoff, and ambiguous metric clarification.

Covered requirements:

| Requirement | Verification |
|---|---|
| `FR-03-001` | `tests/test_semantic_catalog.py` |
| `FR-03-002` | `tests/test_semantic_catalog.py` |
| `FR-03-003` | `tests/test_question_parser.py` |
| `FR-03-004` | `tests/test_sql_generator.py` |
| `FR-03-005` | `tests/test_semantic_catalog.py`, `tests/test_question_parser.py`, `tests/test_semantic_pipeline.py` |
| `FR-03-006` | `tests/test_question_parser.py` |
| `FR-03-007` | `tests/test_semantic_pipeline.py` |
| `FR-03-008` | `tests/test_semantic_catalog.py` |
| `AC-03-001` | `revenue` and `sales amount` resolve to the same canonical metric |
| `AC-03-002` | Missing time expression defaults to last 30 days |
| `AC-03-003` | Ambiguous metric term returns clarification and no SQL |
| `AC-03-004` | Generated SQL includes an SQL explanation |
| `TC-03-001` | Synonym dictionary maps known aliases to canonical metrics |
| `TC-03-002` | Parser returns expected date range for last-30-day behavior |
| `TC-03-003` | SQL template produces expected revenue aggregation SQL |
| `TC-03-004` | NL question to SQL to Guardrail handoff succeeds |
| `TC-03-005` | Ambiguous metric term returns clarification prompt, not SQL |

## Latest Local Verification

Environment:

```text
Virtual environment: .venv
Python: 3.14.0
```

Layer 1 static check:

```bash
.venv/bin/python -m pyright
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Layer 2 test suite:

```bash
.venv/bin/python -m pytest
```

Result:

```text
88 passed, 1 warning
```

Known warning:

```text
StarletteDeprecationWarning from fastapi.testclient
```

This warning comes from the third-party FastAPI/TestClient stack and does not indicate a failing project test.

## Next Slice

Recommended next implementation slice:

```text
question parser
high-sensitivity field denial
  -> sensitive metric/field metadata
  -> policy denial
  -> no SQL generated
```

This would start covering `NFR-03-003`, `AC-03-005`, and `TC-03-006`.
