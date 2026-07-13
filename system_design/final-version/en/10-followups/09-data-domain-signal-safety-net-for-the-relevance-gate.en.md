# 10.9 A Data-Domain-Signal Safety Net for the File-Branch Relevance Gate

## 1. Problem Solved

[10.8](08-question-relevance-gate-before-file-branch-routing.en.md) §6 flagged its own gate as a heuristic, not an understanding: `question_references_attached_file()` only catches literal token overlap between a question and a file's column names/filename. A question that genuinely concerns the attached file but uses different vocabulary than its schema — a business synonym like "territory" for a column literally named `region`, or "order volume" for a column named `orders` — shares no token with the file at all and gets misrouted to the main orchestrator, which has no file data to answer from either. This document closes that specific gap: before trusting a "not relevant" verdict, corroborate it with a second, independent signal, rather than acting on token overlap alone.

## 2. What Already Existed

10.8's gate, wired into `chat_query_v2()`:

```python
route_to_file_branch = bool(effective_file_ids) and question_references_any_attached_file(
    str(body["question"]), effective_files
)
```

Separately, `QuestionClassifier` (`src/chatbi/orchestration/routing.py`) already exists and is used elsewhere in this same request path (`_handle_file_data_chat_query` calls `question_classifier.classify(question)` to decide whether to also layer in knowledge-base RAG evidence). Its `classify()` method computes `has_data_signal` from a `_DATA_DOMAIN_KEYWORDS` list — `revenue`, `order`, `orders`, `refund`, `active users`, `support`, `ticket`, `case volume`, `total`, `count`, `how many`, `average`, `sum`, `rate` — but that intermediate value was private, not exposed, and folded into a `needs_sql` computation (`has_data_signal or is_chart or is_analytics or not is_rag`) whose final `TaskType.SQL_QUERY` result is true for nearly any question by default, via the `or not is_rag` fallback — not a usable discriminator on its own for this purpose.

## 3. A Design That Was Corrected Before It Shipped

The first version of this fix, described to the user before implementation, proposed corroborating a "not relevant" verdict with `resolve_federated_pg_context()` (`business_table_catalog.py`) — reasoning: if that function also finds no real business table for the question, assume the question is probably about the attached file after all, phrased differently, and stay in the file branch as the safer default.

Checking this against the exact reported bug's question before writing any code disproved it. `resolve_federated_pg_context()`'s docstring is explicit about its own matching rule: "Matches only if the question mentions the table's name (underscored or spaced)." The reported question, "Compare total ticket count by product in H1 2026.", never contains the literal string `support_ticket_summary` or `support ticket summary` — so this function returns `None` for it, exactly as it does for a question genuinely unrelated to any business table. Using "no federated match" as the safety-net trigger would have meant: for the *exact* case 10.8 was built to fix, the safety net fires and routes back into the file branch — silently undoing 10.8's own fix for its own motivating bug.

The error was conflating two different questions: "is there a real business table this question could join the file against" (narrow, literal-name-matching, what `resolve_federated_pg_context` actually checks) versus "does this question read like a real business-data question at all, independent of any file" (broader, what was actually needed here). `QuestionClassifier._DATA_DOMAIN_KEYWORDS` already answers the second question — it was already sitting in the codebase, just not exposed as a standalone check.

## 4. Design: Exposing the Narrower Signal, Not the Composite One

`QuestionClassifier` gained one new public method that reads the existing keyword list directly, without going through `classify()`'s broader, mostly-always-true composite:

```python
def has_data_domain_signal(self, question: str) -> bool:
    return self._contains_any(question.strip().lower(), self._DATA_DOMAIN_KEYWORDS)
```

The routing gate in `chat_query_v2()` now reads it as a corroborating check, only when 10.8's token-overlap gate has already said "not relevant":

```python
if not route_to_file_branch and effective_files and not question_classifier.has_data_domain_signal(
    str(body["question"])
):
    route_to_file_branch = True
```

Read as a decision table:

| Token-overlap gate | Data-domain keyword present | Outcome |
|---|---|---|
| Relevant | — | File branch (unchanged from 10.8) |
| Not relevant | Yes | Main orchestrator — corroborated: this reads as a real business-data question, independent of the file |
| Not relevant | No | File branch (overridden) — neither signal found anywhere else for this to go; trust the file branch's own schema-grounded LLM over a guess |

For the reported bug ("...ticket count by product..."), `has_data_domain_signal` is `True` (`ticket`, `total`, `count` all match) — the safety net does not fire, and 10.8's fix still routes away exactly as intended. For a synonym-phrased, genuinely file-relevant question ("Please describe my figures for this cycle.") with no domain keyword and no schema-token overlap, the safety net fires and keeps the request in the file branch.

## 5. Verification

New unit tests (`tests/test_agent_orchestration_routing.py`) cover `has_data_domain_signal` directly: `True` for the reported bug's exact question, `False` for a vague, vocabulary-free question ("How's it looking overall?").

A new HTTP-level test (`tests/test_chat_query_with_files.py::test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch`) attaches a `month`/`revenue` file and asks "Please describe my numbers for this cycle." — no literal overlap with the schema or filename, no data-domain keyword — and asserts `table_result_source == "file"`, proving the safety net kept it in the file branch. The existing 10.8 regression test (the reported bug's own question, asserting `table_result_source is None`) continues to pass unchanged, confirming the safety net does not reopen the original hole.

Reproduced live against a rebuilt Docker image with a real OpenAI-backed LLM client, in the same session structure as 10.8's own verification:

- The original reported question still returns `table_result_source: None`, answered correctly from `business.support_ticket_summary`.
- "Please describe my figures for this cycle.", asked against the real `regional_sales_h1_2026.csv` file with no literal schema overlap, returns `table_result_source: "file"` and a correct, fully-grounded answer computed from the file's actual rows.

All 1360 tests that do not require a live Postgres connection or a built frontend bundle pass; the pre-existing unrelated failure count and identity are unchanged from 10.8's own verification.

## 6. Known Limitations — Not Fixed Here

- **Still a keyword list, not an understanding.** `_DATA_DOMAIN_KEYWORDS` is a fixed, English-only, hand-maintained list. A business-data question phrased with vocabulary outside that list, that also happens to share no token with the attached file's schema, still falls through to the safety net's default — which, per §4's table, means staying in the file branch rather than reaching the main orchestrator. That default was chosen deliberately (§4: "trust the file branch's own schema-grounded LLM over a guess"), but it means this fix narrows 10.8's original hole without fully closing the class of vocabulary-mismatch problems 10.8 §6 first flagged — it only closes the specific instances where `_DATA_DOMAIN_KEYWORDS` happens to provide the corroborating signal.
- **The two remaining gaps 10.8 §6 identified are still open.** Per-file relevance filtering inside a mixed structured+unstructured selection, and `FileDataAgent`'s lack of visibility into a column's actual stored value format, are unrelated to this fix and are covered by their own forward-looking design documents ([10.10](10-per-file-relevance-filtering-in-mixed-selections.en.md), [10.11](11-value-sample-aware-schema-context.en.md)).

## 7. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-077 | `QuestionClassifier` MUST expose a standalone `has_data_domain_signal(question)` check reading only its `_DATA_DOMAIN_KEYWORDS` list, independent of `classify()`'s broader, near-always-true `TaskType.SQL_QUERY` composite. | Implemented |
| NFR-FV10-026 | When the file-branch relevance gate (10.8) judges a question "not relevant" to any attached file, the routing decision MUST be corroborated against `QuestionClassifier.has_data_domain_signal()` before committing to route away from the file branch; absent that corroborating signal, the request MUST stay in the file branch instead. | Implemented |

## 8. Status: Fixed and Verified

The design initially proposed for this fix was checked against the reported bug's own question before any code was written, found to be backwards for that exact case, and corrected to use `QuestionClassifier`'s existing keyword signal instead of `resolve_federated_pg_context()` — the same kind of correction-before-merge this project's SDD+TDD convention exists to surface, applied here one step earlier than usual (at design-review time rather than after a test run). Fixed in `src/chatbi/orchestration/routing.py` and `src/chatbi/api/http.py`; covered by new tests in `tests/test_agent_orchestration_routing.py` and `tests/test_chat_query_with_files.py`; verified end-to-end against a rebuilt Docker image with a real LLM provider, per §5. This design was subsequently written up as [Spec FV10.9](../../../../spec/final-version/en/10-followups/09-data-domain-signal-safety-net-for-the-relevance-gate.spec.en.md), turning it into formal `MUST` requirements, acceptance criteria, and a traceability matrix mapping directly onto the real test names above — spec-after-implementation here, rather than spec-before like Spec FV10.6, since this fix was itself found and fixed the same live-reproduction way Spec FV10.5's defects were.
