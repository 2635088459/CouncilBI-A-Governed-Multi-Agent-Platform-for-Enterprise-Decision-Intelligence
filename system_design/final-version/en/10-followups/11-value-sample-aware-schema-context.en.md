# 10.11 Value-Sample-Aware Schema Context for File SQL Generation

## 1. Problem Solved

Live verification of [10.8](08-question-relevance-gate-before-file-branch-routing.en.md)/[10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.en.md)'s routing fix, against a real OpenAI-backed LLM client, surfaced a related but distinct defect. A same-session follow-up — "What is my revenue by region?" then "What about just June?" — correctly stayed in the file branch (routing worked as intended) but returned an empty `table_result`. The generated SQL was:

```sql
SELECT region, SUM(revenue) AS total_revenue
FROM file_ufile_7b27e853fb394ba4818885d6a7b3a3ee
WHERE month = 'June'
```

against a file whose `month` column actually stores `'2026-01'`..`'2026-06'`. Zero rows matched — a valid-but-empty result, the same *symptom* [10.7](07-cross-turn-value-format-contamination-in-file-sql-generation.en.md) diagnosed, but a different *cause*: 10.7's fix (an explicit prompt instruction, plus a narrower conversation-history window) only addresses a value format carried over from an *earlier turn*. Here, "June" was typed directly into the *current* question — there is no prior turn to blame, and no history-window fix can help. The model guessed a plausible-sounding literal because it had no way to know the file's actual format: `build_schema_context()` told it a column's *name* and *type* (`month VARCHAR`), never a sample of what it actually stores.

## 2. What Already Existed

- **`FileDataAgent.build_schema_context(files)`** (`src/chatbi/agents/file_data_agent.py`) — already built the exact string handed to the SQL-generation prompt, from `file.schema_json["columns"]`. This is the function this design changed.
- **`FederatedQueryAgent._build_schema_context()`** — already delegates the file side of its own schema string to `self._file_data_agent.build_schema_context(files)`, keeping the business-table side (`db_{table_name}(...)`) separate. Extending the delegated method automatically flows through to the federated path with no separate change there — and, just as importantly, leaves the business-table side untouched, which matters for §5.
- **`SchemaSerializer.to_json(table)`** (`src/chatbi/files/parser_structured.py`) — already computes `schema_json` once, at upload-processing time (`FileProcessingWorker._process_structured`), from the fully-parsed in-memory `table` before it is written to Parquet. This is the natural place to compute value samples too: the full column data is already in memory at this point, so no new file read or DuckDB query was needed at all — sampling is a Python-side operation on data already loaded for schema inference.

## 3. Design: Samples Computed Once at Upload Time, Not Per Query

Rather than querying the file's Parquet snapshot for samples on every chat turn (extra DuckDB round-trips, extra latency on the hot path), samples are computed once, alongside the schema itself, when the file is first processed — the same point that already computes column names and types:

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
            return entry  # numeric/date types are not the ambiguous case this fixes
        distinct = sorted({row[column.name] for row in rows if row.get(column.name) is not None})
        if not distinct:
            return entry
        if len(distinct) <= SAMPLE_CARDINALITY_THRESHOLD:
            entry["sample_values"] = distinct[:SAMPLE_SIZE]
        else:
            entry["sample_range"] = [distinct[0], distinct[-1]]
        return entry
```

This only touches `VARCHAR` columns — a `BIGINT`/`DOUBLE` value like `150000` is not ambiguous the way a date-shaped string is; the whole problem this design addresses is specifically "a string column whose format the model has to guess."

`build_schema_context()` then reads whichever key is present:

```python
# src/chatbi/agents/file_data_agent.py
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

For the motivating file's actual 6-value `month` column, this produces `month VARCHAR [e.g. '2026-01', '2026-02', '2026-03', '2026-04', '2026-05']` — see §4 for why the sixth value, `'2026-06'`, is not literally present, and why that turned out not to matter.

## 4. A Discrepancy Found While Writing the Test, Not the Code

The motivating file's `month` column has exactly 6 distinct values (`'2026-01'` through `'2026-06'`) — comfortably under `SAMPLE_CARDINALITY_THRESHOLD` (20), so it takes the `sample_values` branch, not `sample_range`. `SAMPLE_SIZE` (5) then caps that list to the first five sorted values — `'2026-01'`..`'2026-05'` — silently dropping `'2026-06'`, the exact value the motivating question ("What about just June?") needs.

This means the schema context never literally contains the string a correct `WHERE month = '2026-06'` needs to match. Writing the end-to-end test (§6) surfaced this before any live verification did: a naive fake LLM client that checks "does the prompt contain the literal target value" would never see it, and the test would be unwritable as originally imagined in this design's own earlier draft (which assumed, incorrectly, that the 6-value case would take the `sample_range` branch and reveal a `'2026-01'..'2026-06'` range). The fake client's condition was redesigned to check whether the schema context reveals the column's *format* at all (a regex match for an ISO-date-shaped token, e.g. `\d{4}-\d{2}`) rather than whether it contains the *specific literal* being asked about — simulating a model that generalizes a format from examples rather than one that must see every value verbatim.

Live verification against a real OpenAI-backed LLM confirmed this is exactly what happens in practice: given `month VARCHAR [e.g. '2026-01', '2026-02', '2026-03', '2026-04', '2026-05']` and the question "What about just June?", the model correctly produced `WHERE month = '2026-06'` — inferring the sixth value's format from the five present, not requiring it to be enumerated. This is the reasoning `SAMPLE_SIZE`'s existence already assumed (§7 of this design's earlier draft asked whether the constants were "the right tuning," not whether the underlying mechanism — generalizing from examples — was sound); the live check confirms the assumption, for this case, was correct.

## 5. Deliberately Not Touching the Business-Table Side

`FederatedQueryAgent._build_schema_context()`'s `db_line` — the governed business table's schema string — is built entirely separately, from `PostgresQueryContext.columns` (already filtered through `business_table_catalog.py`'s `safe_columns_for_role()` deny/mask policy), and does not call `build_schema_context()` at all. This design's changes flow only through the file side of that delegation. That separation is deliberate, not incidental: `safe_columns_for_role()` only decides *which columns exist* in the schema string handed to the LLM — it has no equivalent policy for *whether a column's actual values* may be disclosed. A `mask`-policy column (e.g. a redacted email field) that is nonetheless in the "safe to see the column exists" set would, under a naive extension of this design to the business-table side, leak real values into the SQL-generation prompt through a path the masking policy was never built to cover. This design intentionally stays scoped to a user's own uploaded file — where the same values already reach the LLM post-execution via `answer_synthesis.py`'s grounding context, so no new trust boundary is crossed — and leaves the business-table side for a separate design if it is ever needed, one that would first need to extend `access_policies` with a values-may-be-sampled flag, not just a column-visibility one.

## 6. Verification

New unit tests: `SchemaSerializer.to_json()` produces `sample_values` for a low-cardinality `VARCHAR` column, `sample_range` for a high-cardinality one, and neither key for a numeric column (`tests/test_structured_file_parser.py`); `FileDataAgent.build_schema_context()` renders each suffix correctly, and renders a column with neither key exactly as before (`tests/test_file_data_agent.py`). Two pre-existing tests with exact-equality assertions on `schema_json` (`tests/test_structured_file_parser.py::test_schema_serializer_produces_columns_list_of_name_type_objects` and `tests/test_file_processing_worker.py::test_process_structured_file_produces_ready_status_schema_and_parquet_snapshot`) needed their expected values updated to include the new `sample_values` key — an expected, intentional change in behavior, not a regression.

The end-to-end test (`tests/test_chat_query_with_files.py::test_a_month_literal_typed_into_the_current_question_uses_the_files_real_format`) reproduces §1's motivating case with the format-conditional fake LLM client described in §4, and fails against the pre-fix `build_schema_context()` for the intended reason. A regression test (`tests/test_federated_query_agent.py::test_business_table_schema_line_is_unaffected_by_a_files_value_samples`) confirms `FederatedQueryAgent`'s `db_line` is byte-identical whether or not the attached file's `schema_json` carries samples.

Reproduced live against a rebuilt Docker image with a real OpenAI-backed LLM client: a freshly-uploaded file's `schema_json` correctly showed `sample_values` (verified via `GET /api/v2/files`); the same two-turn session from §1 — "What is my revenue by region?" then "What about just June?" — now returns the correct seeded revenue figure for June, with the model correctly inferring `'2026-06'` from the five present examples, confirming §4's design choice under real conditions, not just the test double's simulation of it.

## 7. Known Limitations — Not Fixed Here

- **`SAMPLE_CARDINALITY_THRESHOLD = 20` / `SAMPLE_SIZE = 5` are still starting guesses**, not tuned against real file distributions. §4 shows the mechanism tolerates `SAMPLE_SIZE` truncating a legitimate value out of the list (the model generalizes the format instead) — but that is a property observed for one realistic case with a real LLM, not a guarantee for every column shape. A file with many low-cardinality `VARCHAR` columns could still grow the schema string meaningfully.
- **`sample_range` still applies to every high-cardinality `VARCHAR` column, including freeform text ones** (e.g. a `notes` field) that would get a technically-correct but not meaningful `[min..max]` pair. This is harmless — not wrong, just unhelpful — but a cheap pre-check (reusing [10.8](08-question-relevance-gate-before-file-branch-routing.en.md)'s own `_GENERIC_DATE_TOKEN`/`_MONTH_NAME_TOKEN`-style patterns rather than reinventing one) to skip the annotation for columns unlikely to benefit remains unimplemented.
- **A column with genuinely mixed formats within itself** (some rows `'2026-06'`, others `'June 2026'`, from a messy real-world upload) still leaves the model to reconcile inconsistent examples on its own — this design gives the model a representative sample of what a column actually contains, not a guarantee it always infers or reconciles the correct format from it.

## 8. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-080 | `SchemaSerializer.to_json()` MUST compute, for each `VARCHAR` column, either a capped list of distinct sample values (when distinct count is at or below a configured threshold) or a `[min, max]` range (when above it), computed once from the fully-parsed table at upload-processing time, not re-queried per chat turn. | Implemented |
| FR-FV10-081 | `FileDataAgent.build_schema_context()` MUST render a column's `sample_values`/`sample_range`, when present in `schema_json`, as part of the schema string handed to SQL-generation, and MUST render a column with neither key exactly as it does today. | Implemented |
| FR-FV10-082 | This enhancement MUST NOT alter `FederatedQueryAgent`'s business-table (`db_{table_name}`) schema string in any way — only the file side of its delegated schema context may include value samples. | Implemented |
| NFR-FV10-028 | This enhancement MUST NOT require a query-time DuckDB round-trip beyond what `FileDataAgent`/`FederatedQueryAgent` already perform, and MUST NOT require backfilling `schema_json` for files uploaded before this change. | Implemented |

## 9. Status: Implemented and Verified

Implemented per this project's usual SDD+TDD order: [Spec FV10.11](../../../../spec/final-version/en/10-followups/11-value-sample-aware-schema-context.spec.en.md) was written first, its test cases written and confirmed to exercise the intended behavior, then `SchemaSerializer`/`FileDataAgent` were changed to make them pass. §4 documents a real discrepancy found while writing the end-to-end test — between this design's own earlier assumption about which branch (`sample_values` vs `sample_range`) the motivating case would take, and what the constants as specified actually produce — corrected before implementation was called done, then confirmed sound against a real LLM. Fixed in `src/chatbi/files/parser_structured.py` and `src/chatbi/agents/file_data_agent.py`; covered by new tests in `tests/test_structured_file_parser.py`, `tests/test_file_data_agent.py`, `tests/test_chat_query_with_files.py`, and `tests/test_federated_query_agent.py`, plus two pre-existing tests updated for the intentional `schema_json` shape change; verified end-to-end against a rebuilt Docker image with a real LLM provider, per §6. §7's limitations were identified during the same work and are intentionally left for a future followup.
