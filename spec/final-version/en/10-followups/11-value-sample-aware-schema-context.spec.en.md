# Spec FV10.11: Value-Sample-Aware Schema Context for File SQL Generation

Source design:
- [10.11 Value-Sample-Aware Schema Context for File SQL Generation design](../../../../system_design/final-version/en/10-followups/11-value-sample-aware-schema-context.en.md)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (parent spec; this spec revises `SchemaSerializer.to_json()` and `FileDataAgent.build_schema_context()`, both first specified there)
- [10.7 Cross-Turn Value-Format Contamination in File/Federated SQL Generation design](../../../../system_design/final-version/en/10-followups/07-cross-turn-value-format-contamination-in-file-sql-generation.en.md) — no dedicated Spec FV10.7 exists for this one either; it was implemented directly from its design doc, the same way 10.8's was (see Spec FV10.9's header note for the same pattern). This spec's motivating failure (§1) produces the identical *symptom* that design doc diagnosed — valid-but-empty SQL from a value-format mismatch — from a different *cause*, and neither this spec nor that fix closes the other's cause.

---

## 1. Purpose

Live verification of Spec FV10.9's routing fix, against a real LLM provider, surfaced a same-symptom, different-cause sibling of the defect [10.7's design doc](../../../../system_design/final-version/en/10-followups/07-cross-turn-value-format-contamination-in-file-sql-generation.en.md) diagnosed. A follow-up question typed directly by the user in the *current* turn — "What about just June?" — against a file whose `month` column stores `'2026-01'`..`'2026-06'`, produced `WHERE month = 'June'`: valid SQL, zero matching rows. 10.7's fix (a prompt instruction plus a narrower conversation-history window) does not apply here — there is no prior turn to blame; the model guessed a plausible-sounding literal because `FileDataAgent.build_schema_context()` gave it a column's name and type only, never a sample of what it actually stores.

This spec defines the fix: compute a small set of representative values (or, for high-cardinality columns, a value range) for each `VARCHAR` column once, at file-upload-processing time, and include them in the schema string handed to SQL generation.

## 2. Scope

**In scope:**
- Extending `SchemaSerializer.to_json()` (`src/chatbi/files/parser_structured.py`) to compute, for each `VARCHAR` column, either a capped list of distinct sample values or a `[min, max]` range, from the fully-parsed in-memory table already available at upload-processing time.
- Extending `FileDataAgent.build_schema_context()` (`src/chatbi/agents/file_data_agent.py`) to render whichever of those two is present in a column's `schema_json` entry.
- Preserving byte-identical `build_schema_context()` output for a column with neither key present — the shape every file uploaded before this spec has.

**Out of scope:**
- Any query-time DuckDB sampling — this spec computes samples once, at upload time, not per chat turn (§6.1).
- Any change to `FederatedQueryAgent._build_schema_context()`'s business-table (`db_{table_name}`) schema line — this spec's changes flow only through the file side of that method's existing delegation to `FileDataAgent.build_schema_context()` (§5 of the source design; FR-FV10-082 below).
- Backfilling `schema_json` for files uploaded before this spec — an existing file simply keeps its current (sample-free) schema string until re-uploaded.
- Tuning `SAMPLE_CARDINALITY_THRESHOLD`/`SAMPLE_SIZE` against real-world file distributions, or adding a pre-check to skip `sample_range` for freeform-text columns unlikely to benefit from it — both remain open questions the source design (§7) leaves for a future followup, not requirements this spec fixes a value for.

## 3. Actors

Reuses the actors defined in the parent FV-10 spec §3. No new actor.

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-080 | `SchemaSerializer.to_json(table)` MUST, for each column whose inferred type is `VARCHAR`, compute from that column's fully-parsed values: a `sample_values` list of up to `SAMPLE_SIZE` distinct values when the column's distinct-value count is at or below `SAMPLE_CARDINALITY_THRESHOLD`, or a `sample_range` pair `[min, max]` (lexicographic) when above it. This computation MUST happen once, from the in-memory `table` already available during upload processing, and MUST NOT be re-derived by any code path that runs per chat query. A column with zero non-null values MUST receive neither key. A column whose inferred type is not `VARCHAR` MUST receive neither key. |
| FR-FV10-081 | `FileDataAgent.build_schema_context(files)` MUST render, for each column, `f"{name} {type}"` followed by `f" [e.g. {sample_values...}]"` when `schema_json`'s column entry has a `sample_values` key, or `f" [{low}..{high}]"` when it has a `sample_range` key, or no suffix at all when it has neither. |
| FR-FV10-082 | This spec's changes MUST NOT alter `FederatedQueryAgent._build_schema_context()`'s `db_line` (the business-table schema string built from `PostgresQueryContext.columns`) in any way, for any input. Only the file side of that method's existing delegation to `FileDataAgent.build_schema_context()` may include value samples. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV10-028 | This spec's changes MUST NOT introduce any DuckDB query, or any other read of a file's Parquet snapshot, beyond what `FileDataAgent`/`FederatedQueryAgent` already perform at chat-query time — FR-FV10-080's computation MUST be fully contained within the existing upload-processing pipeline (`FileProcessingWorker._process_structured`, via `SchemaSerializer.to_json()`), which already holds the full parsed table in memory before this spec's changes and before the row-count limit check that can reject the upload. This spec MUST NOT require a migration or backfill step for `schema_json` on any file uploaded before this spec is implemented; `build_schema_context()` MUST treat the absence of `sample_values`/`sample_range` on such a file's columns as valid input, not an error. |

## 6. Data Contracts

### 6.1 `SchemaSerializer` — Computing Samples Once, at Upload Time

```python
# src/chatbi/files/parser_structured.py
SAMPLE_CARDINALITY_THRESHOLD = 20
SAMPLE_SIZE = 5

class SchemaSerializer:
    def to_json(self, table: ParsedTable) -> dict[str, Any]:
        return {"columns": [self._column_json(column, table.rows) for column in table.columns]}

    def _column_json(self, column: ColumnSchema, rows: tuple[Mapping[str, Any], ...]) -> dict[str, Any]:
        entry: dict[str, Any] = {"name": column.name, "type": column.type}
        if column.type != "VARCHAR":
            return entry
        distinct = sorted({row[column.name] for row in rows if row.get(column.name) is not None})
        if not distinct:
            return entry
        if len(distinct) <= SAMPLE_CARDINALITY_THRESHOLD:
            entry["sample_values"] = distinct[:SAMPLE_SIZE]
        else:
            entry["sample_range"] = [distinct[0], distinct[-1]]
        return entry
```

`to_json(table)` reads `table.rows` — the same fully-parsed, in-memory rows `ParquetWriter.write()` consumes immediately afterward in `FileProcessingWorker._process_structured()`. No new file read, no new DuckDB connection.

### 6.2 `FileDataAgent.build_schema_context()` — Rendering Samples

```python
# src/chatbi/agents/file_data_agent.py
def build_schema_context(self, files: tuple[UserUploadedFile, ...]) -> str:
    lines: list[str] = []
    for file in files:
        assert file.schema_json is not None
        columns = file.schema_json["columns"]
        column_defs = ", ".join(self._column_def(column) for column in columns)
        lines.append(f"file_{file.file_id}({column_defs})")
    return "\n".join(lines)

def _column_def(self, column: Mapping[str, object]) -> str:
    piece = f"{column['name']} {column['type']}"
    if "sample_values" in column:
        examples = ", ".join(repr(value) for value in column["sample_values"])
        return f"{piece} [e.g. {examples}]"
    if "sample_range" in column:
        low, high = column["sample_range"]
        return f"{piece} [{low!r}..{high!r}]"
    return piece
```

A column dict with neither `sample_values` nor `sample_range` — the shape of every column in every `schema_json` produced before this spec was implemented — renders exactly as it did before: `f"{name} {type}"`, no suffix.

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-080 | `SchemaSerializer.to_json(table)` for a `VARCHAR` column whose parsed values contain `N <= SAMPLE_CARDINALITY_THRESHOLD` distinct non-null strings produces a `schema_json` column entry with a `sample_values` key equal to the sorted distinct values, capped at `SAMPLE_SIZE`. |
| AC-FV10-081 | `SchemaSerializer.to_json(table)` for a `VARCHAR` column whose parsed values contain more than `SAMPLE_CARDINALITY_THRESHOLD` distinct non-null strings produces a `schema_json` column entry with a `sample_range` key equal to `[min(distinct), max(distinct)]` under lexicographic ordering, and no `sample_values` key. |
| AC-FV10-082 | `SchemaSerializer.to_json(table)` for a `BIGINT` or `DOUBLE` column produces a `schema_json` column entry with neither a `sample_values` nor a `sample_range` key, regardless of that column's cardinality. |
| AC-FV10-083 | `FileDataAgent.build_schema_context(files)` for a file whose `schema_json` column entry has `sample_values: ["US-East", "US-West"]` renders that column as `region VARCHAR [e.g. 'US-East', 'US-West']` (or an equivalent `repr()`-quoted rendering) within the returned schema string. |
| AC-FV10-084 | `FileDataAgent.build_schema_context(files)` for a file whose `schema_json` column entry has `sample_range: ["2026-01", "2026-06"]` renders that column as `month VARCHAR ['2026-01'..'2026-06']` (or an equivalent rendering) within the returned schema string. |
| AC-FV10-085 | `FileDataAgent.build_schema_context(files)` for a file whose `schema_json` column entries have neither key (the shape of a file uploaded before this spec) renders identically to the pre-spec output — `f"{name} {type}"`, no suffix, for every such column. |
| AC-FV10-086 | Given a file whose `month` column is seeded with values `'2026-01'`..`'2026-06'` (6 distinct values — below `SAMPLE_CARDINALITY_THRESHOLD`, so per AC-FV10-080 its `schema_json` carries `sample_values` capped to the first 5 sorted entries, `'2026-01'`..`'2026-05'`, not `sample_range` — see §10 for why this spec's own first draft assumed otherwise), a chat request asking "What about just June?" in a session whose prior turn already queried this file produces a non-empty `table_result` whose rows are drawn from June's actual seeded data — using a fake LLM client configured to return a literal-correct `WHERE month = '2026-06'` only when its received prompt's schema-context string reveals the column's date format (an ISO-date-shaped token is present, via either `sample_values` or `sample_range`), and an incorrect `WHERE month = 'June'` otherwise, so that the test fails if the schema-context change described in FR-FV10-081 is not actually reaching the model. The client's condition checks for format revelation, not for the literal target value `'2026-06'` itself being present — that value is not literally in the sample for this exact test fixture, by design (see §10). |
| AC-FV10-087 | `FederatedQueryAgent._build_schema_context()`'s returned `db_line` for a given `PostgresQueryContext` is byte-identical whether or not the file(s) also passed to it have `sample_values`/`sample_range` entries in their `schema_json` — this spec's changes have no observable effect on the business-table half of that method's output. |

## 8. Test Plan

### 8.1 Unit Tests — `SchemaSerializer` Sample Computation

| ID | Layer | Description |
|---|---|---|
| TC-FV10-189 | unit | `SchemaSerializer().to_json(table)` for a parsed table with a `VARCHAR` column seeded with 4 distinct values (`"US-West"`, `"US-East"`, `"US-West"`, `"EU"`) produces a `sample_values` entry equal to the 3 distinct values, sorted (AC-FV10-080). Implemented as `tests/test_structured_file_parser.py::test_schema_serializer_adds_sample_values_for_a_low_cardinality_varchar_column`. |
| TC-FV10-190 | unit | `SchemaSerializer().to_json(table)` for a parsed table with a `VARCHAR` column seeded with 30 distinct values produces a `sample_range` entry equal to `[sorted_values[0], sorted_values[-1]]`, and no `sample_values` key (AC-FV10-081). Implemented as `tests/test_structured_file_parser.py::test_schema_serializer_adds_sample_range_for_a_high_cardinality_varchar_column`. |
| TC-FV10-191 | unit | `SchemaSerializer().to_json(table)` for a parsed table with `BIGINT`/`DOUBLE` columns produces column entries with no `sample_values`/`sample_range` key (AC-FV10-082). Implemented as `tests/test_structured_file_parser.py::test_schema_serializer_never_adds_sample_keys_to_a_numeric_column`. |

### 8.2 Unit Tests — `FileDataAgent.build_schema_context()` Rendering

| ID | Layer | Description |
|---|---|---|
| TC-FV10-192 | unit | `FileDataAgent().build_schema_context(files)` for a file whose `schema_json` has `sample_values: ["US-East", "US-West"]` on its `region` column includes `"region VARCHAR [e.g. 'US-East', 'US-West']"` in the returned string (AC-FV10-083). Implemented as `tests/test_file_data_agent.py::test_build_schema_context_renders_a_sample_values_suffix`. |
| TC-FV10-193 | unit | `FileDataAgent().build_schema_context(files)` for a file whose `schema_json` has `sample_range: ["2026-01", "2026-06"]` on its `month` column includes `"month VARCHAR ['2026-01'..'2026-06']"` in the returned string (AC-FV10-084). Implemented as `tests/test_file_data_agent.py::test_build_schema_context_renders_a_sample_range_suffix`. |
| TC-FV10-194 | unit | `FileDataAgent().build_schema_context(files)` for a file whose `schema_json` columns have neither key produces a string byte-identical to `FileDataAgent`'s pre-spec output for the same input (AC-FV10-085) — this is the regression test proving existing files' behavior is unaffected. Implemented as `tests/test_file_data_agent.py::test_build_schema_context_reflects_schema_json`. |

### 8.3 Integration Test — The Motivating Failure, Fixed

| ID | Layer | Description |
|---|---|---|
| TC-FV10-195 | integration (HTTP) | Reproduces this spec's §1 motivating case end-to-end: a two-turn session against a file seeded with `region`/`month`/`revenue` rows (`month` values `'2026-01'`..`'2026-06'`), second turn asking "What about just June?", against a format-conditional fake LLM client wired as described in AC-FV10-086. Asserts `table_result` is non-empty and matches June's seeded row (AC-FV10-086). This test fails against the pre-spec `build_schema_context()`, since the fake LLM client is deliberately configured to only produce correct SQL when given a schema-context string revealing the column's date format — a fixed-SQL test double that always returns correct SQL regardless of prompt content would not catch a regression to this spec's core mechanism, which is exactly why this test's fake client is prompt-conditional rather than fixed-output. Implemented as `tests/test_chat_query_with_files.py::test_a_month_literal_typed_into_the_current_question_uses_the_files_real_format`. |

### 8.4 Regression Test — Business-Table Schema Line Unaffected

| ID | Layer | Description |
|---|---|---|
| TC-FV10-196 | regression | `FederatedQueryAgent`'s schema-context construction, exercised once with a file whose `schema_json` carries no samples and once with a file whose `schema_json` carries a `sample_range`, produces a `db_line` (the substring of the captured SQL-generation prompt starting `db_{table_name}(`) that is byte-identical in both cases, for the same `PostgresQueryContext` (AC-FV10-087). Implemented as `tests/test_federated_query_agent.py::test_business_table_schema_line_is_unaffected_by_a_files_value_samples`. |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-080 | AC-FV10-080, AC-FV10-081, AC-FV10-082 | TC-FV10-189, TC-FV10-190, TC-FV10-191 |
| FR-FV10-081 | AC-FV10-083, AC-FV10-084, AC-FV10-085 | TC-FV10-192, TC-FV10-193, TC-FV10-194 |
| FR-FV10-082 | AC-FV10-087 | TC-FV10-196 |
| NFR-FV10-028 | AC-FV10-085, AC-FV10-086 | TC-FV10-194, TC-FV10-195 |

## 10. Implementation Notes

- **AC-FV10-086 was corrected before this spec's first version was called done.** The originally-drafted AC-FV10-086 assumed the motivating case's 6-distinct-value `month` column would take the `sample_range` branch (per AC-FV10-081) and reveal a `'2026-01'..'2026-06'` range containing the exact literal the test needed. Writing TC-FV10-195 surfaced that this is wrong: 6 is below `SAMPLE_CARDINALITY_THRESHOLD` (20), so the column takes the `sample_values` branch instead, and `SAMPLE_SIZE` (5) caps that list to `'2026-01'`..`'2026-05'` — `'2026-06'` itself, the value the test's question asks about, is never literally present in the schema context. A test whose fake LLM client checked for that literal's presence would be unwritable as originally conceived. The fake client's condition was redesigned to check for format revelation (a regex match for an ISO-date-shaped token) rather than for the specific literal — simulating a model that generalizes a format from examples, not one that must see every value verbatim. Live verification against a real OpenAI-backed LLM (system design §4/§6) confirmed this simulation matches real behavior: given the 5-example list, the model correctly produced `'2026-06'` for the value not shown.
- This is the same class of correction Spec FV10.9's own §10 and Spec FV10.10's own §10 each represent — a design checked against reality and found to need revision — but caught at the earliest point yet in this project's pattern: while writing the *test itself*, before that test was ever run against real code, let alone before any live reproduction. FV10.9's correction was caught by checking a proposed design against a reported bug's actual question before writing code; FV10.10's was caught by running the *existing* test suite after code and new tests both existed; this correction was caught by trying to write one specific test's fixture data and finding the assumption underlying it didn't hold.
- TC-FV10-189's exact fixture (4 seeded values, 3 distinct after a repeat) and TC-FV10-190's (30 distinct values) were kept deliberately far from `SAMPLE_CARDINALITY_THRESHOLD`'s boundary (20) precisely because AC-FV10-086 already demonstrates what happens *near* that boundary in a case that matters: these two unit tests are for confirming which branch fires in the unambiguous cases, not for exploring the threshold's edge, which AC-FV10-086/TC-FV10-195 already covers by consequence rather than by design.
- Implementing FR-FV10-080 required updating two pre-existing tests with exact-equality assertions on `schema_json` that predate this spec — `tests/test_structured_file_parser.py::test_schema_serializer_produces_columns_list_of_name_type_objects` and `tests/test_file_processing_worker.py::test_process_structured_file_produces_ready_status_schema_and_parquet_snapshot` — both now expect the `sample_values` key their fixture's single-or-few-valued `VARCHAR` column produces. Neither is a regression; both are the exact-equality style of test that will always need updating when a serialized shape intentionally changes, the same pattern noted for `SchemaSerializer.to_json()`'s only other pre-existing caller-facing test.
