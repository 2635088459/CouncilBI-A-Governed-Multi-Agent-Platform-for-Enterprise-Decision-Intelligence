# Spec FV10.10: Per-File Relevance Filtering for Mixed Structured/Unstructured Selections

Source design:
- [10.10 Per-File Relevance Filtering for Mixed Structured/Unstructured Selections design](../../../../system_design/final-version/en/10-followups/10-per-file-relevance-filtering-in-mixed-selections.en.md)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (parent spec; this spec revises `_handle_file_data_chat_query`)
- [Spec FV10.6: Hybrid File Answering for Mixed Structured/Unstructured Selections](06-hybrid-file-answering-for-mixed-selections.spec.en.md) (this spec narrows one case within FR-FV10-064's structured/unstructured split — see §4 FR-FV10-078 — and does not alter any other behavior FR-FV10-064 through FR-FV10-070 establish)
- [Spec FV10.9: A Data-Domain-Signal Safety Net for the File-Branch Relevance Gate](09-data-domain-signal-safety-net-for-the-relevance-gate.spec.en.md) (§10 of this spec records a real interaction this spec's implementation had with FV10.9's own behavior, found by the test suite — see FR-FV10-083)

This spec's prerequisite, 10.8's request-level relevance gate (`question_references_any_attached_file()` / `question_references_attached_file()` in `src/chatbi/agents/file_query_support.py`), is already implemented (design doc only, no dedicated spec — see Spec FV10.9's own header for that same note). This spec reuses `question_references_attached_file()` as-is, applying it at a different call site — it introduces no new relevance-judging logic of its own.

---

## 1. Purpose

Spec FV10.6 (§4 FR-FV10-064) already splits a request's `file_ids` into a structured subset and an unstructured subset before deciding how to answer. The 10.8 gate this spec builds on decides, for the request as a whole, whether to enter `_handle_file_data_chat_query` at all — but once inside, nothing filtered the *structured* subset by relevance the way the request-level gate does in aggregate. A mixed selection where one attached structured file is irrelevant to the question and one attached unstructured file is relevant still handed the irrelevant structured file to `FileDataAgent`/`FederatedQueryAgent`, which have no graceful "not about your data" output — the same failure mode 10.8 fixed at the request level, reachable again for the narrower mixed-selection case 10.8's own aggregate `any(...)` check does not cover.

This spec defines the fix: filter `structured_ids` (Spec FV10.6's own output) down to only the files `question_references_attached_file()` judges relevant, before either `resolve_federated_pg_context()` or `FileDataAgent`/`FederatedQueryAgent` sees them — but only when a genuine unstructured alternative exists (FR-FV10-083; see §10 for why this condition exists).

## 2. Scope

**In scope:**
- Filtering `structured_ids` (as produced by Spec FV10.6's `split_file_ids_by_type()`) inside `_handle_file_data_chat_query`, using the existing `question_references_attached_file()` predicate, before `pg_context` resolution and before either agent runs — only when `unstructured_ids` is non-empty.
- Preserving `unstructured_ids` unfiltered by this predicate.
- Preserving `effective_file_ids` and the session's stored file selection (`session_file_context`) exactly as Spec FV10.4/10.8 already produce them — this filter has no effect on any turn other than the one it runs for.

**Out of scope:**
- Any change to `question_references_attached_file()`/`question_references_any_attached_file()` themselves (Spec FV10.9's scope, unaffected by this spec).
- Any change to `FileScopedRetriever`'s own relevance handling for `unstructured_ids` (Spec FV10.6 §6.2) — explicitly not filtered by this spec; see FR-FV10-079.
- Any change to `resolve_federated_pg_context()`'s own business-table-name-matching logic (`business_table_catalog.py`) — this spec only changes what set of structured files reaches it, not how it decides which table to join.
- `FileDataAgent`/`FederatedQueryAgent`'s own internal behavior once given a (possibly narrowed) `structured_ids` — unchanged.

## 3. Actors

Reuses the actors defined in the parent FV-10 spec §3. No new actor.

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-078 | `_handle_file_data_chat_query` MUST filter `structured_ids`, immediately after `split_file_ids_by_type()` produces it (Spec FV10.6 FR-FV10-064) and before `resolve_federated_pg_context()` is called, down to the subset for which `question_references_attached_file(question, files_by_id[fid])` returns `True`. If this filtering results in an empty `structured_ids`, the request MUST proceed exactly as Spec FV10.6's own "no structured file" path already does (`federated_output = None; file_output = None`, falling through to an evidence-only answer or the pre-existing FR-FV10-066 error). |
| FR-FV10-079 | This filter MUST NOT be applied to `unstructured_ids`. `FileScopedRetriever`'s own per-file relevance handling (Spec FV10.6 §6.2 — an empty result for an irrelevant file, not an error) MUST be the only mechanism governing which unstructured files contribute evidence. |
| FR-FV10-083 | FR-FV10-078's filter MUST NOT run at all when `unstructured_ids` is empty — `structured_ids` MUST pass through unfiltered by this spec in that case. A pure-structured selection MUST be decided solely by Spec FV10.9's request-level safety net, which may deliberately keep a request in the file branch specifically because `structured_ids` has no relevant member by this spec's own predicate and no independent business-data signal exists either; applying this spec's filter in that case would silently re-empty `structured_ids` one call frame after FV10.9 decided to keep it, undoing that decision. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV10-027 | For a request whose every attached structured file already passes `question_references_attached_file()`, this filter MUST produce a `structured_ids` identical (same members, same order) to Spec FV10.6's unfiltered output — this spec MUST NOT alter behavior for that case. This filter MUST NOT modify `effective_file_ids`, and MUST NOT modify the session's stored file selection (`session_file_context`) for any turn — a file removed from one turn's filtered `structured_ids` MUST remain available, unfiltered by this spec, to a later turn's own filtering decision. |

## 6. Data Contracts

### 6.1 `_handle_file_data_chat_query` — Filtered `structured_ids`

```python
files_by_id: dict[str, UserUploadedFile] = {...}  # unchanged (Spec FV10.6)
structured_ids, unstructured_ids = split_file_ids_by_type(file_ids, files_by_id)

# FR-FV10-078/083: per-file relevance filter, reusing Spec FV10.9's
# dependency `question_references_attached_file()` unmodified. Only when
# unstructured_ids is non-empty (FR-FV10-083) — see §10 for why this
# condition is load-bearing, not optional.
if unstructured_ids:
    structured_ids = tuple(
        fid for fid in structured_ids
        if question_references_attached_file(question, files_by_id[fid])
    )

pg_context = (
    resolve_federated_pg_context(question, role, active_business_table_catalog)
    if active_business_table_catalog is not None and structured_ids
    else None
)
```

Everything from `pg_context` onward is Spec FV10.6's own, unmodified control flow (`06-hybrid-file-answering-for-mixed-selections.spec.en.md` §6.5) — this spec's only change is the `if unstructured_ids:`-guarded filter before that control flow begins. `question_references_attached_file`, exported from `chatbi.agents.file_query_support` and re-exported via `chatbi.agents.__init__` alongside `question_references_any_attached_file`, is imported into `http.py`'s existing `from chatbi.agents import (...)` block.

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-075 | A request with `file_ids` = [one structured file relevant to the question, one structured file irrelevant to the question, one unstructured file relevant to the question] produces a `table_result` reflecting only the relevant structured file's data, and the SQL-generation prompt sent to the LLM never contains the irrelevant structured file's `file_id` in its schema-context string. |
| AC-FV10-076 | A request with `file_ids` = [one structured file irrelevant to the question, one unstructured file relevant to the question] produces `table_result_source` equal to `None`, an `evidence_list` containing the unstructured file's evidence, and zero LLM calls of `task_type` `"file_data_sql_generation"` or `"federated_query_sql_generation"`. |
| AC-FV10-077 | A request with `file_ids` = [one structured file irrelevant to the question, one unstructured file whose content is also irrelevant to the question] fails with the same `error.message` Spec FV10.6 FR-FV10-066 already produces for "neither subset produced anything answerable" — unchanged by this spec. |
| AC-FV10-078 | A request with `file_ids` = [one structured file relevant to the question, one unstructured file relevant to the question] (Spec FV10.6's own `test_chat_query_with_a_mixed_structured_and_unstructured_selection_answers_from_both` scenario) produces a response byte-identical to the same request made against a build without this spec's changes applied. |
| AC-FV10-079 | Given a two-turn session where turn 1 attaches a structured file irrelevant to turn 1's question (filtered out of turn 1's `structured_ids` by this spec) alongside a relevant unstructured file, and turn 2 sends no explicit `file_ids` and asks a question relevant to that same structured file, turn 2's `table_result` reflects that structured file's data — the filter's effect on turn 1 does not persist into turn 2's `effective_file_ids` or session-stored selection. |
| AC-FV10-088 | A request with `file_ids` = [one structured file only, phrased with vocabulary its schema does not literally contain, with no independent business-data-keyword signal either] (Spec FV10.9's own motivating case) is answered from the file branch (`table_result_source` equal to `"file"`) — this spec's filter MUST NOT run for a request with no attached unstructured file, and MUST NOT undo Spec FV10.9's safety net. |

## 8. Test Plan

### 8.1 Integration Tests — HTTP, Mixed-Selection Filtering

| ID | Layer | Description |
|---|---|---|
| TC-FV10-184 | integration (HTTP) | `POST /api/v2/chat/query` with `file_ids` = [relevant structured, irrelevant structured, relevant unstructured], using a recording fake LLM client for the file branch's SQL-generation call: asserts the captured system prompt's schema-context string contains the relevant structured file's `file_id` and does not contain the irrelevant one's, and that `table_result` matches only the relevant file's seeded data (AC-FV10-075). The irrelevant file deliberately has no Parquet snapshot written for it — if the filter regressed to querying it anyway, this test fails with a storage lookup error, not a silent wrong assertion. Implemented as `tests/test_chat_query_with_files.py::test_mixed_selection_with_an_irrelevant_structured_file_excludes_it_from_sql_generation`. |
| TC-FV10-185 | integration (HTTP) | `POST /api/v2/chat/query` with `file_ids` = [irrelevant structured, relevant unstructured], using a recording fake LLM client: asserts the recorded call list contains no request with `task_type` in `{"file_data_sql_generation", "federated_query_sql_generation"}`, `table_result_source` is `None`, and `evidence_list` contains the unstructured file's evidence (AC-FV10-076). Implemented as `tests/test_chat_query_with_files.py::test_mixed_selection_with_only_irrelevant_structured_files_skips_sql_generation_entirely`. |
| TC-FV10-186 | integration (HTTP) | `POST /api/v2/chat/query` with `file_ids` = [irrelevant structured, irrelevant-content unstructured] returns the same `error.message` text as Spec FV10.6's own `test_chat_query_with_only_an_unstructured_file_with_irrelevant_content_returns_400` (AC-FV10-077). Implemented as `tests/test_chat_query_with_files.py::test_mixed_selection_with_nothing_relevant_returns_the_pre_existing_unanswerable_error`. |

### 8.2 Regression Test — Already-Relevant Mixed Selection Unaffected

| ID | Layer | Description |
|---|---|---|
| TC-FV10-187 | regression | Spec FV10.6's existing `tests/test_chat_query_with_files.py::test_chat_query_with_a_mixed_structured_and_unstructured_selection_answers_from_both`, re-run unchanged against a build with this spec's filter applied, continues to pass (AC-FV10-078, NFR-FV10-027). |

### 8.3 Multi-Turn Integration Test — Filter Does Not Persist Into Session State

| ID | Layer | Description |
|---|---|---|
| TC-FV10-188 | integration (HTTP, multi-turn) | Two-turn session: turn 1 sends `file_ids` = [structured file X irrelevant to turn 1's question, unstructured file Y relevant to it]; turn 2 sends no `file_ids` (inherits the session's stored selection, which per Spec FV10.4 still includes X) and asks a question relevant to X. Asserts turn 2's `table_result` reflects X's seeded data — proving this spec's per-turn `structured_ids` filtering left `effective_file_ids`/`session_file_context` untouched (AC-FV10-079). Implemented as `tests/test_chat_query_with_files.py::test_a_structured_file_filtered_out_of_one_turn_remains_available_to_a_later_relevant_turn`. |

### 8.4 Regression Test — Spec FV10.9's Safety Net Unaffected

| ID | Layer | Description |
|---|---|---|
| TC-FV10-197 | regression | Spec FV10.9's existing `tests/test_chat_query_with_files.py::test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch` (a single structured file, no unstructured file attached) continues to pass unchanged against a build with this spec's filter applied (AC-FV10-088, FR-FV10-083). This test regressed when this spec's filter was first written without the `if unstructured_ids:` guard — see §10. |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-078 | AC-FV10-075, AC-FV10-076, AC-FV10-077 | TC-FV10-184, TC-FV10-185, TC-FV10-186 |
| FR-FV10-079 | AC-FV10-076 | TC-FV10-185 |
| FR-FV10-083 | AC-FV10-088 | TC-FV10-197 |
| NFR-FV10-027 | AC-FV10-078, AC-FV10-079 | TC-FV10-187, TC-FV10-188 |

## 10. Implementation Notes

- FR-FV10-083 and TC-FV10-197 were not part of this spec's first version. Following §0's TDD guidance, TC-FV10-184 through TC-FV10-188 were written first, confirmed to fail against the unfiltered code for the expected reason, and then FR-FV10-078's filter was implemented without the `if unstructured_ids:` guard now in §6.1. Running the *full* test suite immediately afterward — not just the five new test cases — regressed Spec FV10.9's `test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch`: a single structured file, with vocabulary its schema doesn't literally contain and no independent business-data signal, is exactly the request FV10.9's safety net exists to keep in the file branch. The unconditional filter re-ran the same `question_references_attached_file()` verdict FV10.9's safety net had already overridden at the request level, silently re-emptying `structured_ids` one call frame later and undoing that override. FR-FV10-083 and TC-FV10-197 record the fix and the regression test that would catch it again; both were added to this spec after the correction, not predicted by its first version.
- This is the same class of correction Spec FV10.9's own §10 records (a design checked against reality and found wrong), but caught one step later in the process: FV10.9's correction happened before any code was written, by checking a proposed design against the reported bug's actual question; this spec's correction happened after code and new tests existed, by running the *existing* regression suite. Both are examples of this project's SDD+TDD convention doing its job — the difference is only how early the check happened, not whether it happened before the fix was called done.
- AC-FV10-075's assertion checks for the irrelevant file's `file_id` specifically, not a full `file_{file_id}(...)` schema-line string, because `FileDataAgent.build_schema_context()`'s exact rendering format is Spec FV10.11's concern (proposed, not implemented) — this spec depends only on the `file_id` substring being present or absent from whatever that method currently renders, not on its column-listing format.
- No test in this spec's plan directly exercises `FederatedQueryAgent`'s join path with a filtered `structured_ids` — Spec FV10.6's own federated-path tests (`tests/test_chat_query_federated.py`) do not attach an irrelevant second structured file, and this spec did not add one, since `resolve_federated_pg_context()`'s behavior is unaffected by which structured files reach it (§5 of the source design) — only whether any do at all, which the existing `and structured_ids` guard, unit-tested by Spec FV10.6, already covers.
