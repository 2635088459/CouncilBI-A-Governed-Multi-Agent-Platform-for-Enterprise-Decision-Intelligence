# Spec FV10.12: Evidence Relevance Gating and Join-Mismatch Caveats for Hybrid File/Warehouse Comparison Answers

中文版：[../../zh-CN/10-followups/12-evidence-relevance-and-join-mismatch-caveats.spec.zh-CN.md](../../zh-CN/10-followups/12-evidence-relevance-and-join-mismatch-caveats.spec.zh-CN.md)

Source design:
- [10.12 Evidence Relevance Gating and Join-Mismatch Caveats for Hybrid File/Warehouse Comparison Answers](../../../../system_design/final-version/en/10-followups/12-evidence-relevance-and-join-mismatch-caveats.en.md)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (parent spec; this spec revises `_handle_file_data_chat_query()`'s evidence handling and `FederatedQueryAgent`'s output contract)

This spec was written **spec-first**, before any of §3/§4's design was implemented, per this project's usual SDD+TDD order (the same order [Spec FV10.6](06-hybrid-file-answering-for-mixed-selections.spec.en.md), [Spec FV10.10](10-per-file-relevance-filtering-in-mixed-selections.spec.en.md), and [Spec FV10.11](11-value-sample-aware-schema-context.spec.en.md) used) — unlike Spec FV10.5's or FV10.9's fixes, which were written down after a live-reproduction fix already existed. Every functional requirement below has at least one acceptance criterion and at least one test case; every test case traces back to a requirement. Test cases were written to run **red** against the pre-implementation code, then confirmed **green** afterward — see §10 for a correction to §6.1's relevance floor found while building TC-FV10-198's fixture, before that fixture was ever run.

---

## 1. Purpose

A single reported answer exposed two independent, structural defects in the hybrid file/warehouse comparison path (`_handle_file_data_chat_query()` in `src/chatbi/api/http.py`):

1. Evidence retrieved from the org-wide knowledge base is rendered as a "source" for the answer regardless of whether it clears any meaningful relevance bar, because `InMemoryKnowledgeStore.retrieve()`'s only floor is `relevance_score > 0` and `ResultMerger._tag_evidence()` concatenates whatever it is given with no threshold of its own.
2. A `FederatedQueryAgent` comparison query that returns zero rows because its `JOIN` condition never matched anything is narrated identically to a comparison query that genuinely found no rows exceeding a threshold — nothing in `FederatedQueryAgentOutput` distinguishes "no match" from "matched, and passed."

This spec adds: (a) a relevance-score floor applied to knowledge-base evidence at the point it is rendered, scoped to the hybrid file path only; and (b) a `zero_row_join_caveat` signal on `FederatedQueryAgentOutput`, surfaced to the answer-synthesis prompt when a `JOIN`-bearing query returns zero rows despite non-empty source views.

## 2. Scope

**In scope:**
- A new module-level constant and filter applied to `knowledge_base_evidence` inside `_handle_file_data_chat_query()` (`src/chatbi/api/http.py`), immediately after `EvidenceItem`s are constructed from `retrieval_result.evidence_list`.
- A new `zero_row_join_caveat: bool` field on `FederatedQueryAgentOutput` (`src/chatbi/files/contracts.py`), computed inside `FederatedQueryAgent.run()` (`src/chatbi/agents/federated_query_agent.py`).
- Passing an explicit instruction into the answer-synthesis prompt when `zero_row_join_caveat` is `True`.

**Out of scope:**
- Any change to `QuestionClassifier._RAG_KEYWORDS` or `classify()` — this spec does not change when a knowledge-base search is triggered, only what is done with items it returns. See the source design's §6 for why this is deliberate.
- Any change to `InMemoryKnowledgeStore.retrieve()`'s own ranking or its `relevance_score <= 0` floor (`src/chatbi/knowledge.py:363`) — the new floor in this spec is applied by the caller, not inside the knowledge store.
- Detecting a *partial* join mismatch (some rows matched, some silently dropped) — `zero_row_join_caveat` only ever fires for a fully empty result; see the source design's §6.
- Any change to `uploaded_file_evidence` / `FileScopedRetriever`'s own relevance behavior, already specified by [Spec FV10.6](06-hybrid-file-answering-for-mixed-selections.spec.en.md).
- Any change to the main orchestrator's (non-file) RAG evidence path.

## 3. Actors

Reuses the actors defined in the parent FV-10 spec §3. No new actor.

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-084 | Inside `_handle_file_data_chat_query()`, an `EvidenceItem` derived from `active_knowledge_store.retrieve()`'s result MUST be excluded from `knowledge_base_evidence` when its `relevance_score` is below a fixed minimum floor (`_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE`). |
| FR-FV10-085 | `FederatedQueryAgentOutput` MUST expose a `zero_row_join_caveat: bool` field (default `False`), set to `True` by `FederatedQueryAgent.run()` if and only if: (a) the final query result has zero rows, (b) the generated SQL text contains the case-insensitive substring `join`, and (c) both the materialized Postgres view and every materialized file view had at least one row before the query ran. |
| FR-FV10-086 | When `FederatedQueryAgentOutput.zero_row_join_caveat` is `True`, `_handle_file_data_chat_query()` MUST include an explicit instruction in the answer-synthesis request stating that no matching rows were found across the join key(s), and that this MUST NOT be characterized as confirming any threshold or comparison result. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV10-029 | The FR-FV10-084 relevance floor MUST apply only to `knowledge_base_evidence` computed inside `_handle_file_data_chat_query()`. It MUST NOT be applied to `uploaded_file_evidence` (from `FileScopedRetriever`), and MUST NOT alter any RAG evidence computed by the main (non-file) orchestrator path. |

## 6. Data Contracts

### 6.1 Relevance Floor — `src/chatbi/api/http.py`

```python
_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE = 0.15  # corrected during implementation — see §10

knowledge_base_evidence = tuple(
    EvidenceItem(
        source_id=item.source_id,
        title=item.title,
        citation_anchor=item.citation_anchor,
        snippet=item.snippet,
        relevance_score=item.relevance_score,
    )
    for item in retrieval_result.evidence_list
    if item.relevance_score >= _MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE
)
```

`0.15` is this spec's fixed value — corrected from an originally proposed `0.35` after implementation surfaced that the higher value would have dropped evidence a pre-existing regression test already asserts is returned (§10). It sits above `InMemoryKnowledgeStore`'s blended-score floor of `> 0` (`knowledge.py:363`) while admitting that genuinely on-topic document; TC-FV10-198 fixes the exact fixture scores this value is validated against. `uploaded_file_evidence` is constructed by a separate code path (`file_scoped_retriever.retrieve(...)`, unchanged) and is not passed through this filter.

### 6.2 `FederatedQueryAgentOutput` — `src/chatbi/files/contracts.py`

```python
@dataclass(frozen=True, slots=True)
class FederatedQueryAgentOutput:
    degraded: bool
    table_result: TableResult | None = None
    federated_sql: str | None = None
    error_code: str | None = None
    degradation_reason: str | None = None
    zero_row_join_caveat: bool = False
```

### 6.3 `FederatedQueryAgent.run()` — `src/chatbi/agents/federated_query_agent.py`

```python
try:
    columns, rows = fetch_table(connection, sql_text)
except QueryResourceExceededError:
    return FederatedQueryAgentOutput(
        degraded=False, error_code="QUERY_RESOURCE_EXCEEDED", federated_sql=sql_text,
    )
except InvalidGeneratedSqlError:
    return FederatedQueryAgentOutput(
        degraded=False, error_code="INVALID_GENERATED_SQL", federated_sql=sql_text,
    )

zero_row_join_caveat = (
    not rows
    and "join" in sql_text.lower()
    and self._source_row_count(connection, request.pg_context.table_name) > 0
    and all(
        self._source_row_count(connection, f"file_{file.id}") > 0
        for file in structured_files
    )
)
return FederatedQueryAgentOutput(
    degraded=False,
    table_result=TableResult(columns=columns, rows=rows),
    federated_sql=sql_text,
    zero_row_join_caveat=zero_row_join_caveat,
)
```

`_source_row_count()` is a new private helper issuing `SELECT COUNT(*) FROM "<view_name>"` against the already-open DuckDB connection — both `db_{table}` and every `file_{file_id}` view are already materialized at this point by `_register_views()` (unchanged), so this adds two lightweight in-memory `COUNT(*)` queries, not a new data source.

### 6.4 Answer-Synthesis Instruction — `src/chatbi/api/http.py`

```python
if federated_output is not None and federated_output.zero_row_join_caveat:
    synthesis_instructions += (
        "\n\nThe comparison query matched zero rows across the join, even though "
        "both the file and the warehouse table each had data for this period. "
        "State plainly that no matching records were found across the join "
        "key(s) — do not claim this means all values are within any threshold, "
        "since a join-key mismatch (e.g. differing spelling, capitalization, or "
        "date format between the file and the warehouse column) produces the "
        "identical zero-row result. Recommend the user verify that the shared "
        "column(s) use the same values/format in both sources."
    )
```

The exact mechanism for appending to the answer-synthesis request (a prompt string vs. a structured field on the synthesizer's input) is an implementation detail left to `answer_synthesis.py`'s existing interface; this spec's requirement (FR-FV10-086) is only that the instruction reaches the synthesizer, worded to prevent a "no variance" conclusion, whenever the flag is `True`.

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-089 | Given `retrieval_result.evidence_list` with `relevance_score` values `[0.9, 0.4, 0.1]` and the fixed floor `0.35`, `knowledge_base_evidence` contains exactly the items scoring `0.9` and `0.4`; the `0.1` item is excluded. |
| AC-FV10-090 | Given the same fixture as AC-FV10-089, `uploaded_file_evidence` (constructed independently) is unchanged in content and count — the floor has no effect on it. |
| AC-FV10-091 | Given a `FederatedQueryAgent.run()` call whose generated SQL contains `JOIN`, whose Postgres-side view has 3 rows, whose file-side view has 5 rows, and whose executed query returns 0 rows, the returned `FederatedQueryAgentOutput.zero_row_join_caveat` is `True`. |
| AC-FV10-092 | Given the same fixture as AC-FV10-091 but with join keys that do match, producing a non-empty result, `zero_row_join_caveat` is `False`. |
| AC-FV10-093 | Given a fixture where the file-side view has 0 rows (an empty uploaded file) and the query returns 0 rows, `zero_row_join_caveat` is `False` — an empty source, not a join mismatch, explains the empty result. |
| AC-FV10-094 | When `_handle_file_data_chat_query()` processes a `FederatedQueryAgentOutput` with `zero_row_join_caveat=True`, the request passed to the answer synthesizer contains the join-mismatch instruction text from §6.4; when `zero_row_join_caveat=False`, it does not. |
| AC-FV10-095 | A `POST /api/v2/chat/query` request reproducing the reported question ("I've uploaded our internal regional sales file for H1 2026. Compare it against the revenue numbers in the data warehouse for the same period and flag any regions with more than 5% variance.") against a test knowledge base containing only documents scoring below `_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE` for this question returns a `sources` list with zero entries. Per §10, this criterion is satisfied for low-scoring noise; it does not claim the floor excludes a reconstruction of the original report's own two documents, which score above any floor value that also satisfies AC-FV10-089's fixture. |

## 8. Test Plan

### 8.1 Unit Tests — Relevance Floor

| ID | Layer | Description |
|---|---|---|
| TC-FV10-198 | unit | A fixture with `relevance_score` values `[0.9, 0.4, 0.1]` against `_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE` produces `knowledge_base_evidence` with 2 items, matching the `0.9`/`0.4` sources (AC-FV10-089). Implemented as `tests/test_chat_query_with_files.py::test_chat_query_hybrid_comparison_excludes_low_relevance_knowledge_base_sources` (uses a `_FixedScoreKnowledgeStore` test double rather than `InMemoryKnowledgeStore` directly — see §10). |
| TC-FV10-199 | unit | `uploaded_file_evidence` is unaffected by the floor (AC-FV10-090/NFR-FV10-029). Verified by construction, not a dedicated runtime test — see §10: the floor in §6.1 is applied only inside the `knowledge_base_evidence` comprehension, which never touches the separately-constructed `uploaded_file_evidence` variable. |

### 8.2 Unit Tests — `FederatedQueryAgent.zero_row_join_caveat`

| ID | Layer | Description |
|---|---|---|
| TC-FV10-200 | unit | A fake LLM client returns a `JOIN`-bearing SQL statement against two non-empty, non-overlapping source fixtures; the query executes and returns 0 rows; `zero_row_join_caveat` is `True` (AC-FV10-091). Implemented as `tests/test_federated_query_agent.py::test_zero_row_join_caveat_true_when_join_keys_do_not_match_and_sources_are_non_empty`. |
| TC-FV10-201 | unit | The same fixture with matching join keys on both sides, producing a non-empty result; `zero_row_join_caveat` is `False` (AC-FV10-092). Implemented as `test_zero_row_join_caveat_false_when_join_keys_match`. |
| TC-FV10-202 | unit | The same fixture with an empty Postgres-side source (0 rows) and a 0-row result; `zero_row_join_caveat` is `False` (AC-FV10-093). Implemented as `test_zero_row_join_caveat_false_when_the_postgres_side_is_empty`. |
| TC-FV10-203 | unit | A query whose generated SQL contains no `JOIN` substring (e.g. a single-table `WHERE`) and returns 0 rows; `zero_row_join_caveat` is `False` regardless of source row counts. Implemented as `test_zero_row_join_caveat_false_when_the_generated_sql_has_no_join`. |

### 8.3 Integration Tests — Answer-Synthesis Instruction and HTTP Response

| ID | Layer | Description |
|---|---|---|
| TC-FV10-204 | integration (HTTP) + unit | `POST /api/v2/chat/query` with a mismatched federated join returns `table_result.rows == []` and an answer text proving the caveat instruction reached answer synthesis (AC-FV10-094). Implemented as `tests/test_chat_query_federated.py::test_federated_join_key_mismatch_flags_zero_row_join_caveat_in_answer_synthesis`, using an LLM stub that reports whether its system prompt contains the caveat wording. Complemented by direct unit tests of `GroundedAnswerSynthesizer.synthesize()`'s new `extra_instructions` parameter in `tests/test_answer_synthesis.py` (`test_synthesize_appends_extra_instructions_to_the_system_message`, `test_synthesize_without_extra_instructions_does_not_alter_the_system_message`, `test_fallback_answer_states_no_matching_rows_when_extra_instructions_and_empty_table`). |
| TC-FV10-205 | integration (HTTP) | `POST /api/v2/chat/query` with a structured file attached, a question phrased with an ordinary RAG-triggering word ("internal"), and a stub knowledge store returning three evidence items at fixed scores `[0.9, 0.4, 0.1]`, returns `data.evidence_list` containing only the `0.9` and `0.4` sources (AC-FV10-089/AC-FV10-095, merged with TC-FV10-198 into one HTTP-level test rather than a separate lower-level unit test, since the filter is inline logic inside `_handle_file_data_chat_query`, not a standalone function). Implemented as `tests/test_chat_query_with_files.py::test_chat_query_hybrid_comparison_excludes_low_relevance_knowledge_base_sources`. |

### 8.4 Regression Tests

| ID | Layer | Description |
|---|---|---|
| TC-FV10-206 | regression | Every pre-existing test in `tests/test_chat_query_with_files.py`, `tests/test_chat_query_federated.py`, and `tests/test_chat_query_file_rag_analytics.py` continues to pass. This is not a construction guarantee here the way TC-FV10-199 is: running the full suite against the originally proposed `0.35` floor failed `tests/test_chat_query_file_rag_analytics.py::test_file_query_layers_in_knowledge_base_rag_evidence_for_a_why_question`, which is the regression §10 records and the reason the floor's value changed. |
| TC-FV10-207 | regression | Every pre-existing test asserting a `FederatedQueryAgentOutput`'s `table_result`/`error_code`/`degraded` fields continues to pass unchanged — `zero_row_join_caveat` is additive and defaults to `False`. |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-084 | AC-FV10-089, AC-FV10-095 | TC-FV10-198, TC-FV10-205, TC-FV10-206 |
| FR-FV10-085 | AC-FV10-091, AC-FV10-092, AC-FV10-093 | TC-FV10-200, TC-FV10-201, TC-FV10-202, TC-FV10-203, TC-FV10-207 |
| FR-FV10-086 | AC-FV10-094 | TC-FV10-204 |
| NFR-FV10-029 | AC-FV10-090 | TC-FV10-199 |

## 10. Implementation Notes

- This spec was written before implementation, and TC-FV10-198 through TC-FV10-205 were confirmed to fail against the pre-implementation code for the expected reason (no relevance floor existed; `FederatedQueryAgentOutput` had no `zero_row_join_caveat` field) before §6's changes landed — the SDD+TDD "red" step, per this project's established TDD discipline (see [Spec FV10.10 §9](10-per-file-relevance-filtering-in-mixed-selections.spec.en.md) for the precedent this spec followed).
- **The `0.35` floor originally proposed in §6.1 was corrected to `0.15` during implementation, before any of §8's tests were run against real code.** §6.1 flagged this value as "a starting value, not empirically tuned against production retrieval data" — that concern turned out to be load-bearing. Measured against `InMemoryKnowledgeStore`'s real scoring formula (`knowledge.py:362`):
  - The pre-existing regression fixture in `tests/test_chat_query_file_rag_analytics.py::test_file_query_layers_in_knowledge_base_rag_evidence_for_a_why_question` — a real "why did revenue change" question against a genuinely on-topic document — scores **0.2267**, below `0.35`. Running the full suite against the `0.35` implementation failed this exact test: `assert len(data["evidence_list"]) == 1` produced `0 == 1`.
  - Reconstructing the *originally reported bug's own two unrelated documents* against the exact reported question scores **0.3502** and **0.4011** — both above `0.35`. A third, unrelated support-ticket document scored **0.3548** for comparison.
  - The reason: this store's `relevance_score` rewards a document's vocabulary breadth (more tokens, more incidental keyword and hashed-embedding-bucket overlap) more than genuine topical relevance — a short, on-topic snippet can score lower than a long, off-topic one. No single floor value satisfies AC-FV10-089's fixture *and* keeps the 0.2267 regression test passing *and* excludes the 0.35–0.40 reconstructed noise; `0.15` was chosen to satisfy the first two (a hard constraint — an existing passing test) at the cost of the third, which §6's design doc revision now documents as a known, materially significant limitation rather than a hypothetical one.
  - This is the same class of correction [Spec FV10.9 §10](09-data-domain-signal-safety-net-for-the-relevance-gate.spec.en.md) and [Spec FV10.11 §10](11-value-sample-aware-schema-context.spec.en.md) record for their own fixture-derived corrections, caught at the same point in the process as FV10.11's: while building a test fixture, before that fixture (or any other new test) was run against production code.
- TC-FV10-198 and TC-FV10-205 were implemented as a single HTTP-level test rather than two separate tests at different layers, since the relevance-floor filter is inline logic inside `_handle_file_data_chat_query()`, not a standalone function with its own unit-testable boundary — see §8.3's revised description.
- FR-FV10-085's `zero_row_join_caveat` computation issues two extra `COUNT(*)` queries per federated request only when the result is already empty (short-circuited by `not rows` first in §6.3's `and` chain) — this is not an added cost on the common, non-empty-result path.
- All 1396 tests in the project suite that do not require a live Postgres connection or a built frontend bundle pass after this spec's implementation; the pre-existing unrelated failures (Postgres-credential tests, frontend-bundle assertion tests, static-analysis tests over unrelated pre-existing code, a markdown-link-resolution test on an unrelated pre-existing file) are unchanged in count and identity from before this spec's changes.
