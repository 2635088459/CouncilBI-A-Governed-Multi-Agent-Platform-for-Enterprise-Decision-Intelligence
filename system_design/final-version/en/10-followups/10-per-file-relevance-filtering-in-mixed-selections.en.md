# 10.10 Per-File Relevance Filtering for Mixed Structured/Unstructured Selections

## 1. Problem Solved

[10.8](08-question-relevance-gate-before-file-branch-routing.en.md) added `question_references_any_attached_file()` as a routing-level gate: the *entire* request stays out of the file branch when none of the attached files are relevant to the question. But the gate is deliberately all-or-nothing per request, not per file — `question_references_any_attached_file()` returns `True` (keep the request in the file branch) as soon as *any* attached file is unstructured, regardless of whether any attached *structured* file is actually relevant:

```python
def question_references_any_attached_file(question, files):
    if any(file.schema_json is None for file in files):
        return True
    return any(question_references_attached_file(question, file) for file in files)
```

Concretely: a user attaches `regional_sales_h1_2026.csv` (structured, irrelevant to the question) alongside `nimbus_product_onepager.pdf` (unstructured, relevant) and asks "What is the product's pricing strategy?" The PDF is genuinely relevant, so the request correctly stays in the file branch — but `_handle_file_data_chat_query` still hands the *entire* `structured_ids` subset, including the irrelevant CSV, to `FileDataAgent`. Nothing inside that function re-checks per-file relevance the way the outer routing gate does. The same failure mode 10.8 fixed at the request level — the LLM either invents a plausible-looking mapping onto the wrong columns, or writes SQL that doesn't bind — can still happen here, just now co-existing with a correct PDF-sourced answer instead of failing the whole request.

## 2. What Already Existed

Everything this design needed was already built, just not wired together for this specific case:

- **`question_references_attached_file(question, file)`** (`src/chatbi/agents/file_query_support.py`) — already took one file and returned a per-file relevance verdict. 10.8 only ever called it inside `question_references_any_attached_file()`'s aggregate `any(...)`; nothing called it to filter a list down to its relevant members.
- **`split_file_ids_by_type(file_ids, files_by_id)`** (10.6) — already separates `structured_ids` from `unstructured_ids` before either subset is handed to an agent. This design adds one more filtering step immediately after that split, not a new mechanism.
- **The "no structured file" fallback path** (`_handle_file_data_chat_query`, 10.5/10.6) — already handles `structured_ids == ()` gracefully: `federated_output = None; file_output = None`, falling through to an evidence-only answer if `unstructured_ids` produced anything, or the existing FR-FV10-066 error if nothing did. Filtering `structured_ids` down to `()` lands in this already-tested path, not a new one.

## 3. Design: Filter `structured_ids` Immediately After the Split — Only for Genuine Mixed Selections

```python
files_by_id: dict[str, UserUploadedFile] = {...}  # unchanged
structured_ids, unstructured_ids = split_file_ids_by_type(file_ids, files_by_id)

# Drop any structured file this specific question shows no relevance to,
# the same predicate 10.8 already uses at the request level — just applied
# per file instead of aggregated with `any(...)`. Only when unstructured_ids
# is also non-empty (§4).
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

Everything downstream of this point is unchanged: `pg_context` resolution already only runs `if ... and structured_ids`, so if filtering empties `structured_ids`, it is skipped automatically — no new conditional needed there. `FederatedQueryAgent`/`FileDataAgent` then only ever see the structured files this question actually looks relevant to.

This filter is a no-op for two of the three cases 10.8 already covers at the request level:

- **All attached files structured, all irrelevant** — 10.8's outer gate already keeps this request out of `_handle_file_data_chat_query` entirely; this filter never runs.
- **All attached files structured, at least one relevant** — 10.8's outer gate lets the request through; `unstructured_ids` is empty, so the `if unstructured_ids:` guard (§4) keeps this filter from running at all — the multi-structured-file, partially-relevant case this design originally called out as new, uncovered behavior turned out to need explicitly *excluding*, not including, once §4's interaction with 10.9 was found.
- **Mixed selection, unstructured present** — the case in §1: 10.8's outer gate always lets the request through when any unstructured file is present; this is the case where this filter has its main, intended effect.

## 4. The Interaction With 10.9 That the Test Suite Caught

The first version of this filter ran unconditionally on `structured_ids`, with no `if unstructured_ids:` guard. Running the full test suite after writing it — not just the new tests written for this fix — immediately regressed [10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.en.md)'s own `test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch`: a single structured file, phrased with vocabulary its schema doesn't literally contain, with no independent business-data-keyword signal either. 10.9's whole reason for existing is to keep exactly this request in the file branch — trusting `FileDataAgent`'s own schema-grounded LLM over routing it to a main orchestrator equally unlikely to help. Applying this design's filter unconditionally re-ran the identical `question_references_attached_file()` check that 10.9's safety net had *already* overridden at the request level, silently re-emptying `structured_ids` and undoing that override one call frame later.

The fix is the `if unstructured_ids:` guard in §3: this filter only has a legitimate reason to run when there is a genuine alternative — unstructured evidence — for the request to fall back on if a structured file is excluded. A pure-structured selection has no such alternative; excluding its only file leaves the request with nothing, which is strictly worse than letting `FileDataAgent` take an educated guess, the exact tradeoff 10.9 already made deliberately. This also resolves §3's second bullet from the original version of this design (a multi-structured-file, partially-relevant selection with no unstructured file) in the opposite direction than first assumed: that case is now explicitly *not* filtered, for the same reason a single-structured-file selection isn't.

## 5. Interaction With `FederatedQueryAgent`

`resolve_federated_pg_context()` does not depend on any file's schema — only on the question text and the live business-table catalog — so filtering `structured_ids` before it runs cannot change *which* business table it resolves, only *whether* there is still a structured file left to join that table against (via the existing `and structured_ids` guard). If a mixed request attaches a structured file relevant to the file-join intent alongside an irrelevant one, this filter correctly narrows `FederatedQueryAgent`'s join to the relevant file alone, instead of asking the LLM to reason about a schema that includes an unrelated second file's columns too.

## 6. Verification

New HTTP-level tests (`tests/test_chat_query_with_files.py`): a mixed selection with one relevant structured file, one irrelevant structured file, and one relevant unstructured file, asserting via a recording fake LLM client that the irrelevant file's `file_id` never appears in the SQL-generation prompt and `table_result` reflects only the relevant file; a mixed selection with only an irrelevant structured file and a relevant unstructured file, asserting zero `file_data_sql_generation`/`federated_query_sql_generation` LLM calls happened at all; a mixed selection where nothing is relevant, asserting the pre-existing FR-FV10-066 error is unchanged; and a two-turn session proving a structured file filtered out of one turn remains available, unfiltered, to a later turn asking a genuinely relevant question about it. The irrelevant structured file in each new test deliberately has no Parquet snapshot written for it at all — if the filter regressed to touching that file anyway, the test fails with a storage lookup error, not just a wrong assertion, the same "fail loudly on the actual mechanism" property 10.11's own proposed prompt-conditional fake LLM client (§10 of that design) uses for the same reason.

10.6's own pre-existing mixed-selection test (`test_chat_query_with_a_mixed_structured_and_unstructured_selection_answers_from_both`, both files relevant) was re-run, unchanged, as the regression check for the "already-relevant" case.

Reproduced live against a rebuilt Docker image with a real OpenAI-backed LLM client: a mixed selection (a sales CSV irrelevant to a pricing question, a pricing document relevant to it) returned `table_result_source: None` with the pricing answer correctly grounded in the document alone; the reverse selection (the same two files, a question about the CSV's own data) returned `table_result_source: "file"` with correct, file-sourced revenue figures.

## 7. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-078 | `_handle_file_data_chat_query` MUST filter `structured_ids` (post-`split_file_ids_by_type`) down to only the files `question_references_attached_file()` judges relevant, before either `resolve_federated_pg_context()` or `FileDataAgent`/`FederatedQueryAgent` sees them. | Implemented |
| FR-FV10-079 | This filter MUST NOT apply to `unstructured_ids` — `FileScopedRetriever`'s existing per-file relevance handling (10.6) is unaffected. | Implemented |
| FR-FV10-083 | This filter MUST NOT run at all when `unstructured_ids` is empty. A pure-structured selection MUST be left for 10.9's request-level safety net to decide, unfiltered by this design — found only after the test suite regressed 10.9's own test on this design's first, unconditional version (§4). | Implemented |
| NFR-FV10-027 | This filter MUST NOT alter behavior for a selection where every attached structured file is already relevant (10.6's existing mixed-selection test must remain unaffected), and MUST NOT alter `effective_file_ids` or the session's stored file selection for later turns. | Implemented |

## 8. Status: Implemented and Verified

Implemented per this project's usual SDD+TDD order: [Spec FV10.10](../../../../spec/final-version/en/10-followups/10-per-file-relevance-filtering-in-mixed-selections.spec.en.md) was written first, its test cases were written as failing tests against the pre-fix code and confirmed to fail for the expected reason, then the four-line filter in §3 was added and the tests turned green — with one correction along the way. §4 documents a real regression the project's own test suite caught mid-implementation, the same kind of correction 10.8's month-name-token fix and 10.9's `resolve_federated_pg_context()` correction each represent, just caught one step later than 10.9's (after code and tests existed, by running the *existing* suite, rather than before any code was written). Fixed in `src/chatbi/api/http.py` and `src/chatbi/agents/__init__.py` (exporting `question_references_attached_file`); covered by new tests in `tests/test_chat_query_with_files.py`; verified end-to-end against a rebuilt Docker image with a real LLM provider, per §6.
