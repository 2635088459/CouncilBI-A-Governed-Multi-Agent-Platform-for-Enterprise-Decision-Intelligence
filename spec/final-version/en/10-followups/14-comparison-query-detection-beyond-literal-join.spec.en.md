# Spec FV10.14: Comparison-Query Detection for the Zero-Row Join Caveat, Beyond Literal JOIN Syntax

中文版：[../../zh-CN/10-followups/14-comparison-query-detection-beyond-literal-join.spec.zh-CN.md](../../zh-CN/10-followups/14-comparison-query-detection-beyond-literal-join.spec.zh-CN.md)

Source design:
- [10.14 Comparison-Query Detection for the Zero-Row Join Caveat, Beyond Literal JOIN Syntax](../../../../system_design/final-version/en/10-followups/14-comparison-query-detection-beyond-literal-join.en.md)
- [Spec FV10.12: Evidence Relevance Gating and Join-Mismatch Caveats for Hybrid File/Warehouse Comparison Answers](12-evidence-relevance-and-join-mismatch-caveats.spec.en.md) (parent spec; this spec revises FR-FV10-085's trigger condition only, changing no other requirement in that spec)

This spec was written **after** the fix it describes, following the same order [Spec FV10.5](05-rag-only-routing-and-promotion-durability.spec.en.md) and [Spec FV10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.spec.en.md) used — the defect was found and fixed on the spot via live reproduction against a real, rebuilt Docker deployment, not designed ahead of time. This spec documents and locks in behavior that was already implemented and verified.

---

## 1. Purpose

[Spec FV10.12](12-evidence-relevance-and-join-mismatch-caveats.spec.en.md)'s FR-FV10-085 defines `zero_row_join_caveat` using a literal-substring check (`"join" in sql_text.lower()`) to decide whether a federated query's empty result is a genuine cross-source comparison worth flagging as ambiguous. A live re-test of the exact question that motivated FV10.12 — after FV10.12's own fix had already landed — reproduced the original "no differences" false conclusion, because the model's generated SQL for "compare ... and flag any differences" used `EXCEPT` rather than `JOIN`, evading the literal-substring check entirely. This spec replaces that check with one that inspects what actually determines ambiguity: whether the query references both the business-table view and a file view at all, regardless of which SQL construct it uses to do so.

## 2. Scope

**In scope:**
- Revising `FederatedQueryAgent._compute_zero_row_join_caveat()`'s trigger condition from a literal `"join"` substring match to a check for both source views (`db_{table_name}`, `file_{file_id}`) being referenced in the generated SQL text.

**Out of scope:**
- Any other condition in FR-FV10-085 (empty result, non-empty business-table source, non-empty file source) — unchanged.
- Judging the semantic correctness of the generated comparison SQL itself — this spec only governs whether an empty result gets a caveat, not whether the query that produced it was well-formed. See the source design's §5.
- Any change to the relevance-score floor (`_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE`) or its own known limitations, both already governed by Spec FV10.12.

## 3. Actors

Reuses the actors defined in the parent FV-10 spec §3. No new actor.

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-091 | `FederatedQueryAgent._compute_zero_row_join_caveat()` MUST determine whether a query is a genuine cross-source comparison by checking whether the generated SQL text contains, as a substring, both the business-table view name (`db_{table_name}`) and at least one attached file's view name (`file_{file_id}`) — NOT by searching for the literal substring `"join"`. This supersedes FV10.12's original trigger condition; FR-FV10-085's other three conditions (empty result, non-empty business-table source row count, non-empty file source row counts) are unchanged. |

## 5. Non-Functional Requirements

None beyond FR-FV10-091 above.

## 6. Data Contracts

### 6.1 `FederatedQueryAgent._compute_zero_row_join_caveat()` — `src/chatbi/agents/federated_query_agent.py`

```python
def _compute_zero_row_join_caveat(
    self,
    connection: Any,
    *,
    rows: tuple[Mapping[str, Any], ...],
    sql_text: str,
    pg_table_name: str,
    structured_files: tuple[UserUploadedFile, ...],
) -> bool:
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

Both view-name checks are plain substring tests against the raw `sql_text`, independent of quoting — DuckDB requires a query to name the exact registered view (`db_{table_name}`, `file_{file_id}`) to reference it at all, so this holds for any SQL construct (`JOIN`, `EXCEPT`, `NOT EXISTS`, an anti-join subquery, ...) the model produces.

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-104 | Given a generated SQL statement using `EXCEPT` to compare only the `month` column between a file view and the business-table view (no literal `"join"` substring anywhere in the text), against two non-empty, fully-overlapping-on-`month` source fixtures, and a 0-row final result, `FederatedQueryAgentOutput.zero_row_join_caveat` is `True`. |
| AC-FV10-105 | Given a generated SQL statement that references only the business-table view (never any file view) and returns 0 rows, `zero_row_join_caveat` is `False` — unchanged from FV10.12's original AC-FV10-093-adjacent behavior, now justified by "not a cross-source comparison" rather than "no literal join keyword". |

## 8. Test Plan

| ID | Layer | Description |
|---|---|---|
| TC-FV10-217 | unit | Reproduces the live-reported failure: an `EXCEPT`-on-`month`-only SQL statement, non-empty non-matching-in-content-but-overlapping-in-key source fixtures, 0-row result → `zero_row_join_caveat is True` (AC-FV10-104). Implemented as `tests/test_federated_query_agent.py::test_zero_row_join_caveat_true_for_an_except_comparison_with_no_literal_join_keyword`. |
| TC-FV10-218 | regression | A single-table query referencing only `db_revenue` → `zero_row_join_caveat is False` (AC-FV10-105). Implemented as `tests/test_federated_query_agent.py::test_zero_row_join_caveat_false_when_the_query_only_references_one_source` (renamed from FV10.12's original `..._when_the_generated_sql_has_no_join`; same fixture, updated rationale). |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-091 | AC-FV10-104, AC-FV10-105 | TC-FV10-217, TC-FV10-218 |

## 10. Implementation Notes

- Found via live re-testing of the exact question FV10.12 was written to fix, using a real, rebuilt Docker deployment (`docker compose build backend worker && docker compose up -d --no-deps backend worker`) and a real `gpt-4o-mini`-backed LLM client — not a design review and not a unit-test-writing exercise. The fix and its test were written together, confirmed against the live deployment afterward; see the source design's §4 for the exact reproduction transcript.
- **A deployment gap, not a code gap, caused the first re-test to still show the bug.** FV10.12's code fix had already landed in the source tree when the question was first re-tested, but the running `backend`/`worker` Docker containers were serving an image built roughly 26 hours earlier — `Dockerfile.backend`/`Dockerfile.worker` `COPY` source into the image at build time, so a code change on disk has no effect on a running container until it is rebuilt and restarted. This is recorded here, and in the source design's §6, because it is the reason the first live-verification attempt was misleading, not because it is a defect in this spec's own requirement.
- This spec's traceability is intentionally thin (one FR, two ACs, two TCs) because its scope is a single, narrow correction to one already-specified condition inside an existing requirement (FV10.12's FR-FV10-085), not a new feature — the same proportionate-documentation judgment [Spec FV10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.spec.en.md) applied to its own single-requirement correction.
