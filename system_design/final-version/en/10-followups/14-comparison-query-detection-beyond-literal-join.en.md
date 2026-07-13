# 10.14 Comparison-Query Detection for the Zero-Row Join Caveat, Beyond Literal JOIN Syntax

中文版：[../../zh-CN/10-followups/14-comparison-query-detection-beyond-literal-join.zh-CN.md](../../zh-CN/10-followups/14-comparison-query-detection-beyond-literal-join.zh-CN.md)

## 1. Problem Observed

[10.12](12-evidence-relevance-and-join-mismatch-caveats.en.md) added `zero_row_join_caveat` specifically so a federated comparison that matches nothing would no longer be narrated as a confirmed "no differences" finding. After that fix was deployed, an analyst re-ran the exact question the original report used — *"Compare my uploaded regional sales file against the revenue_by_month table in the data warehouse and flag any differences."* — against the same `regional_sales_h1_2026.csv` file, and got the identical wrong answer again:

> "There are no differences between your uploaded regional sales file and the revenue_by_month table in the data warehouse. The comparison returned zero rows, indicating that the revenue figures match for all regions and months."

This is the same false conclusion 10.12 was written to prevent. `business.revenue_by_month`'s seeded values for 2026-01 through 2026-06 are 1000, 1120, 1180, 1210, 1290, and 1350 (`src/chatbi/migrations.py:210-217`) — three orders of magnitude smaller than the file's per-region monthly revenue (420,000–533,000 for US-West, 398,000–462,000 for US-East). No month's file revenue can equal the warehouse's aggregate revenue for that month; "no differences" is not a plausible true answer for this data, confirming this is a reproduction of the same defect, not a coincidental true negative.

## 2. What Already Existed

`FederatedQueryAgent._compute_zero_row_join_caveat()` (`src/chatbi/agents/federated_query_agent.py`) gated the caveat on a literal substring match:

```python
if rows or "join" not in sql_text.lower():
    return False
```

A question phrased as "compare ... and flag any differences" does not obligate the model to write SQL using `JOIN` syntax at all. Asked to write a comparison, a model routinely reaches for `EXCEPT`, `NOT EXISTS`, or an anti-join subquery instead — none of which contain the literal word "join". A plausible SQL shape for this exact question:

```sql
SELECT month FROM "file_ufile_..." EXCEPT SELECT month FROM "db_revenue_by_month"
```

Both sources cover the identical six months (`2026-01`–`2026-06`), so comparing only the `month` column — never touching `revenue` at all — returns zero rows. This is not a join-key mismatch in the sense 10.12 designed for; it is a different, arguably worse failure: the generated SQL implements a structurally different (and here, wrong) interpretation of "flag differences" — set membership on the key column, not a value comparison — and produces a result that is technically self-consistent (the query really did find zero rows) while still being useless for answering the question asked. Because the SQL text contains no literal "join", `_compute_zero_row_join_caveat()`'s original gate returned `False` before ever reaching the source-row-count checks, and the caveat never had a chance to fire.

## 3. Design: Detect a Genuine Cross-Source Comparison, Not a Keyword

The gate is replaced with a check for what actually matters: does the generated SQL reference both the materialized business-table view and at least one file view at all — regardless of whether it does so via `JOIN`, `EXCEPT`, `NOT EXISTS`, or any other construct DuckDB supports:

```python
if rows:
    return False
references_business_table = f"db_{pg_table_name}" in sql_text
references_a_file = any(
    f"file_{file.file_id}" in sql_text for file in structured_files
)
if not (references_business_table and references_a_file):
    return False
if self._source_row_count(connection, f"db_{pg_table_name}") == 0:
    return False
return all(
    self._source_row_count(connection, f"file_{file.file_id}") > 0
    for file in structured_files
)
```

Both view names are substring-matched against the raw SQL text regardless of quoting — DuckDB requires the query to reference the exact view name it registered (`db_{table_name}`, `file_{file_id}`) to run at all, so this check is robust to whatever join/set-operation syntax the model chose, without needing to parse SQL. `FR-FV10-085`'s original three conditions (empty result, non-empty business-table source, non-empty file source) are otherwise unchanged.

## 4. Verification

A new unit test (`tests/test_federated_query_agent.py::test_zero_row_join_caveat_true_for_an_except_comparison_with_no_literal_join_keyword`) reproduces the exact `EXCEPT`-on-`month`-only SQL shape described in §2 and asserts `zero_row_join_caveat is True`. The pre-existing single-source test (renamed `test_zero_row_join_caveat_false_when_the_query_only_references_one_source`, previously named for "no JOIN keyword") continues to pass, now for the updated reason: it only references `db_revenue`, never any file view, so it is not a cross-source comparison at all. All 15 tests in `tests/test_federated_query_agent.py`, and the full project suite (1397 tests), pass.

The fix was also verified end to end against a live, rebuilt Docker deployment with a real `gpt-4o-mini`-backed LLM client — the container running the reported answer had not been rebuilt after 10.12 landed, which is why the first re-test still reproduced the bug (see §6). After `docker compose build backend worker && docker compose up -d --no-deps backend worker`, re-uploading `regional_sales_h1_2026.csv` and replaying the exact reported question via `POST /api/v2/chat/query` returned:

> "No matching records were found across the join key(s) between your uploaded regional sales file and the revenue_by_month table in the data warehouse. This indicates that there may be a mismatch in the values or formats of the shared columns... I recommend verifying that the `month` column in both sources uses the same values and format."

with an empty `table_result.rows` and `table_result_source: "federated"` — the caveat fired and shaped the live model's answer correctly.

## 5. Known Limitations — Intentionally Not Addressed Here

- **This still cannot judge whether the generated comparison SQL is semantically correct**, only whether a genuinely empty, genuinely cross-source result should be narrated with a caveat instead of a confident conclusion. The live verification in §4 is a case in point: the underlying SQL most likely still implements a naive or partially wrong comparison (e.g. joining on both `month` and `revenue` equality, guaranteeing zero matches given the value-scale mismatch, rather than a `month`-only join with a `revenue`-difference filter) — this fix does not make that SQL *correct*, it only stops the system from asserting a false conclusion when it produces nothing. A truly correct fix for the comparison SQL's own logic is a distinct, harder prompt-engineering problem, out of scope here.
- **The substring check assumes the view names appear literally in the query text.** This holds for every SQL construct DuckDB's `EXPLAIN`-visible grammar supports (a view must be named to be queried), but a sufficiently indirect construction — e.g. a view name built by string concatenation and never appearing as a literal token, or referenced only inside a `PREPARE`d statement DuckDB doesn't support here — would still evade detection. No such case has been observed; this is a theoretical gap, not one this followup found evidence for.
- **10.12's other known limitations (§6 of that document) are unchanged**: the relevance-score floor's calibration gap, and the caveat's silence on partial join mismatches (some rows match, others don't).

## 6. A Deployment Gap Found Alongside the Code Gap

The first re-test of the reported question, after 10.12's code fix had already landed in the source tree, still reproduced the original bug — not because the fix was wrong at that point, but because the running Docker containers (`backend`, `worker`) were serving an image built 26 hours before the fix, and `Dockerfile.backend`/`Dockerfile.worker` `COPY` source code into the image at build time rather than mounting it live. The container had to be rebuilt and restarted before the fix took effect. This is not a defect in this project's code or specs, but it is a real gap in this investigation's own verification process: §4's live-Docker verification step, which 10.7 through 10.11 all performed, was skipped when 10.12 was first implemented, and would have caught this deployment gap immediately. This followup's own §4 verification did rebuild and redeploy before checking — the process this project's own convention already calls for.

## 7. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-091 | `FederatedQueryAgent._compute_zero_row_join_caveat()` MUST determine whether a query is a genuine cross-source comparison by checking whether the generated SQL text references both the materialized business-table view (`db_{table_name}`) and at least one file view (`file_{file_id}`), not by searching for the literal substring `"join"`. | Implemented |

## 8. Status: Fixed and Verified

Found via live re-testing of the exact question 10.12 was written to fix, after 10.12's own code had already landed — a genuine residual gap in that fix's detection heuristic, not a new bug class. Fixed in `src/chatbi/agents/federated_query_agent.py`; covered by a new test in `tests/test_federated_query_agent.py`; verified against a rebuilt Docker deployment with a real OpenAI-backed LLM client per §4. [Spec FV10.14](../../../../spec/final-version/en/10-followups/14-comparison-query-detection-beyond-literal-join.spec.en.md) formalizes this into a single functional requirement, following the same after-the-fact order 10.5 and 10.9 used — this was found and fixed via live reproduction, not designed ahead of time.
