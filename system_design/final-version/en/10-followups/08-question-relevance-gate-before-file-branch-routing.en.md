# 10.8 A Question-Relevance Gate Before Routing to the File Branch

## 1. Problem Solved

A user had `regional_sales_h1_2026.csv` (columns `region`, `month`, `revenue`, `orders`) checked in the sidebar — left over from an earlier turn — and clicked a "Quick Question" shortcut asking "Compare total ticket count by product in H1 2026." The response came back `AGENT_PARTIAL_FAILURE: "The file query could not be completed."` The question has nothing to do with the attached file: there is no ticket or product data in it at all. There is, however, a real `business.support_ticket_summary` table that could have answered it — but the request never reached the code path that could query it.

Reproduced directly against the running container by replaying `FileDataAgent`'s SQL-generation prompt for this exact question and file schema (5 repeats, `temperature=0.0`, identical every time):

```sql
SELECT region, SUM(orders) AS total_orders
FROM file_ufile_7b27e853fb394ba4818885d6a7b3a3ee
WHERE month IN ('2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06')
GROUP BY region;
```

The model, given a schema with nothing resembling "ticket" or "product," substituted the nearest numeric column (`orders`) and answered a different question than the one asked — syntactically valid SQL, semantically wrong. Under a different combination of prior conversation turns (e.g. one that had queried `regional_sales.csv`, a sibling file that does have a `product` column), the same mechanism instead produced SQL referencing a `product` column that does not exist on this file, which DuckDB's binder rejects — `InvalidGeneratedSqlError` — surfacing as the `AGENT_PARTIAL_FAILURE` seen in the report. Both outcomes are symptoms of the same gap: the file this question was forced through cannot answer it, no matter what SQL the model writes.

## 2. What Already Existed

`chat_query_v2()` (`http.py`) made a strictly binary routing decision based on one fact — is `effective_file_ids` non-empty — with no consideration of what the question actually asks:

```python
if effective_file_ids:
    api_envelope = _handle_file_data_chat_query(...)   # file branch only
else:
    api_envelope = chatbi_application.handle_chat_query(...)   # main orchestrator
```

[10.4](04-multi-turn-conversation-memory.en.md) made file attachment session-sticky specifically so a user does not have to re-select a file on every follow-up turn — `resolve_effective_file_ids()` carries the selection forward whenever a request omits `file_ids`. That design choice is exactly what makes a stale, no-longer-relevant selection possible: a file attached three turns ago for a file-specific question is still `effective_file_ids` for an unrelated question five turns later, explicit reselection or not. Neither `FileDataAgent` nor `FederatedQueryAgent` has a "this question isn't about your data" output — [10.6](06-hybrid-file-answering-for-mixed-selections.en.md) gave the *unstructured* side of a mixed selection exactly this behavior (`FileScopedRetriever` simply returns no evidence for irrelevant content, which the caller already handles gracefully), but the *structured* side still had no equivalent: the LLM is always asked to produce a `SELECT`, and it always does, whether or not the schema in front of it has anything to do with the question.

## 3. Design: A Token-Overlap Relevance Predicate, Not an LLM Call

`question_references_attached_file()` (`src/chatbi/agents/file_query_support.py`) decides, without any model call, whether a question plausibly concerns one file:

```python
def question_references_attached_file(question: str, file: UserUploadedFile) -> bool:
    if _tokenize(question) & _FILE_REFERENCE_HINTS:
        return True

    question_tokens = _content_tokens(question)
    if not question_tokens:
        return True

    file_tokens = _content_tokens(file.original_name)
    if file.schema_json is not None:
        for column in file.schema_json["columns"]:
            file_tokens |= _content_tokens(str(column["name"]))

    return bool(question_tokens & file_tokens)
```

Three deliberate exclusions keep this from being a naive bag-of-words match:

- **Stopwords** (`_STOPWORDS`) — "what," "is," "my," "please," "just," etc. — never count as relevance signal in either direction; without this, almost any two English sentences would spuriously "overlap."
- **Generic date/quarter tokens** (`_GENERIC_DATE_TOKEN`, matching bare digits or `h1`/`h2`/`q1`–`q4`) — the reported bug's own file is literally named `regional_sales_h1_2026.csv`, and the broken question ends "...in H1 2026." Without excluding these, the filename match alone would have made the gate say "relevant" for the exact question it needs to say "not relevant" for.
- **Literal month names** (`_MONTH_NAME_TOKEN`, `"january"`...`"december"` and abbreviations) — found only after an early version of this gate broke an *existing* test (§5): "And just June?," asked as a legitimate follow-up against a file whose `month` column stores `"2026-06"`, shares no literal token with that file at all. The column name `month` itself is deliberately **not** in this exclusion list — that is a real, specific schema match; only the calendar-month *value* a user might type is generic enough to exclude.

A fourth rule is the safety net that makes the other three affordable to be strict about: **if, after removing stopwords and generic date/month tokens, nothing content-bearing is left in the question, the gate defaults to relevant.** A pronoun-only follow-up like "What about this one?" has no content tokens left after stopword removal regardless of which file it's asked about — this function cannot judge it, and does not try. It defers to the mechanism that already exists to resolve exactly this case: conversation-history injection (Spec FV10.4).

`question_references_any_attached_file()` is the routing-level wrapper: relevant if *any* attached file is unstructured (its own relevance is `FileScopedRetriever`'s job, per 10.6, not this gate's), or if *any* attached structured file individually passes `question_references_attached_file()`.

## 4. Design: Wiring the Gate Into the Routing Decision

`chat_query_v2()`'s binary choice now has a third input:

```python
effective_files = tuple(
    file for file in (active_file_repository.get(fid) for fid in effective_file_ids) if file is not None
) if effective_file_ids else ()
route_to_file_branch = bool(effective_file_ids) and question_references_any_attached_file(
    str(body["question"]), effective_files
)
if route_to_file_branch:
    ...  # unchanged file branch
else:
    ...  # unchanged main-orchestrator branch
```

When the gate says "not relevant," the request is handled exactly as if `file_ids` had never been sent — `effective_file_ids` itself, and the session's stored selection, are untouched, so a *later*, genuinely file-relevant question in the same session still finds the file attached. Only this one turn's routing decision changes.

## 5. Verification, Including a Self-Caught Regression

Unit tests for the predicate (`tests/test_file_query_support.py`) cover: a column-name match, the reported bug's exact unrelated question, the `h1`/`2026` filename coincidence, a `"file"`/`"uploaded"` hint word, an empty-content pronoun question, and — the one that mattered most — a bare month name.

That last case exists because an earlier version of this gate did not exclude month names, and running the full suite caught it immediately: `tests/test_multi_turn_conversation.py::test_third_turn_inherits_the_second_turns_explicit_file_not_the_first` regressed from pass to fail. Its second turn, `"What about this one?"`, still passed (no content tokens, defaults relevant) — but a related manual check with `"What about just June?"` against a file storing `month` as `"2026-06"` correctly exposed the gap: the gate had no way to distinguish "the question mentions something plausibly this file's own" from "the question mentions a *different*, incompatible way of writing the same kind of thing this file stores." Adding `_MONTH_NAME_TOKEN` to the exclusion list — alongside `just` joining the stopword list, since removing only "june" still left a lone, non-overlapping `"just"` token behind — fixed it without weakening the gate's actual target case.

An HTTP-level regression test (`tests/test_chat_query_with_files.py::test_chat_query_with_a_structured_file_irrelevant_to_the_question_routes_to_main_orchestrator`) reproduces the reported bug directly: a structured file with `month`/`revenue` columns attached, asked an unrelated question, asserts `table_result_source is None` — proof the main orchestrator answered, not the file branch.

Reproduced live against the rebuilt Docker image with the real `regional_sales_h1_2026.csv` file and a real OpenAI-backed LLM client:

- The reported question now returns `table_result_source: None` and a genuine answer computed from `business.support_ticket_summary`, instead of `AGENT_PARTIAL_FAILURE`.
- A same-session follow-up, `"What is my revenue by region?"` then `"What about just June?"`, both return `table_result_source: "file"` — the gate did not misroute the follow-up.

All 1357 tests that do not require a live Postgres connection or a built frontend bundle pass; the pre-existing unrelated failures (Postgres-credential tests, frontend-bundle assertion tests, a markdown-link-resolution test) are unchanged in count and identity from before this change.

## 6. Known Limitations — Not Fixed Here

- **A heuristic, not an understanding.** This is token overlap with a handful of principled exclusions, not semantic matching. A question that genuinely concerns the attached file but shares no vocabulary with its column names or filename (e.g. a question using a business synonym the file's columns don't literally contain) can still be misrouted to the main orchestrator. Unlike [10.7](07-cross-turn-value-format-contamination-in-file-sql-generation.en.md)'s failure mode, a false negative here produces a *differently wrong* answer (or a clean "I don't know" from the orchestrator) rather than a *confidently wrong* one from the file branch — a real improvement in kind, but not a guarantee of always routing correctly.
- **The gate is all-or-nothing per request, not per file.** For a mixed structured+unstructured selection, `question_references_any_attached_file()` keeps the whole request in the file branch as soon as *any* attached file is unstructured or relevant — it does not also filter an irrelevant structured file out of that request's `structured_ids` the way [10.6](06-hybrid-file-answering-for-mixed-selections.en.md) already filters by file *type*. A structured file irrelevant to the question, attached alongside a relevant unstructured one, still reaches `FileDataAgent` and can still produce the same wrong-column or binder-error behavior this document otherwise fixes — just for the mixed-selection case specifically, which was not the reported scenario.
- **A different, still-open problem this investigation surfaced along the way, not fixed by this gate or by 10.7:** even when routing correctly keeps a question in the file branch, `FileDataAgent`'s SQL generation only ever sees a column's *name and type* (`month VARCHAR`), never a sample of its actual stored *values*. A natural-language date reference typed directly into the *current* question — not carried over from an earlier turn, so 10.7's fix does not apply — can still be translated to a literal that does not match the file's real format (e.g. `WHERE month = 'June'` against a column storing `'2026-06'`), producing the same valid-but-empty-result failure 10.7 diagnosed, from a different cause. Closing this would need the schema context handed to the LLM to include a small sample of each column's actual values, not just its declared type — a change to `FileDataAgent.build_schema_context()` and `FederatedQueryAgent`'s equivalent, out of scope here.

## 7. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-074 | `chat_query_v2()` MUST NOT route a request into the file branch (`_handle_file_data_chat_query`) solely because `effective_file_ids` is non-empty; it MUST also confirm at least one attached file is plausibly relevant to the current question, via `question_references_any_attached_file()`. | Implemented |
| FR-FV10-075 | An attached unstructured file MUST always be treated as a valid reason to keep a request in the file branch — its own content relevance is `FileScopedRetriever`'s responsibility (per 10.6), not this gate's. | Implemented |
| FR-FV10-076 | A question with no content-bearing tokens after stopword/generic-date/month-name removal (e.g. a pronoun-only follow-up) MUST default to relevant, deferring to conversation-history resolution (Spec FV10.4) rather than being judged by this gate. | Implemented |
| NFR-FV10-025 | This gate MUST NOT alter `effective_file_ids` or the session's stored file selection when it routes a turn away from the file branch — only that turn's routing decision changes; a later, genuinely relevant question in the same session must still find the file attached. | Verified — `resolve_effective_file_ids()` is called, and the session store updated, before the gate runs; the gate only affects the subsequent `if`. |

## 8. Status: Fixed and Verified

Found via direct production-container reproduction of a user-reported failure, and fixed the same way 10.5 and 10.7 were: no forward design predating the defect. The predicate function and its exclusion lists were also revised mid-implementation after the project's own test suite caught a regression the first version introduced (§5) — the kind of correction this project's SDD+TDD convention exists to surface before merge, not after. Fixed in `src/chatbi/agents/file_query_support.py`, re-exported via `src/chatbi/agents/__init__.py`, and wired into `src/chatbi/api/http.py`; covered by new tests in `tests/test_file_query_support.py` and `tests/test_chat_query_with_files.py`; verified end-to-end against a rebuilt Docker image with a real LLM provider, per §5. §6's limitations were identified during the same investigation and are intentionally left for a future followup.
