# 10.5 RAG-Only Routing and Knowledge Promotion Durability

## 1. Problem Solved

Two defects surfaced during Docker-based end-to-end verification of 10.1–10.4, both in the path between "a document is in the knowledge base" and "RAG actually answers from it":

1. **Every question was gated behind a mandatory SQL step, even pure document questions.** Asking "What does the Nimbus onepager say about pricing?" — a question with nothing to do with any SQL table — still forced the pipeline through SQL generation first. The LLM had nothing sensible to write, produced invalid SQL, the guardrail rejected it, and the whole request was denied before RAG ever ran. `rag_agent` never got a chance to execute.
2. **Promoting a file to the knowledge base could silently produce a permanently-empty, unsearchable document.** A file promoted successfully once could be "promoted" again later — after the backend process had restarted — and instead of failing, it created a real `knowledge.documents` row with zero chunks: present, indexed, but never retrievable by anything, with no error to explain why.

This document covers the design for both fixes.

## 2. What Already Existed

**Routing side:**
- `QuestionClassifier.classify()` unconditionally added `TaskType.SQL_QUERY` to every result set, regardless of question content.
- `ExecutionPlanBuilder.build()` always opened the plan with a SQL step, and every fanout step (RAG, VISUALIZATION, ANALYTICS, FILE_DATA) declared `depends_on=(AgentName.SQL,)` unconditionally.
- `PlanExecutor.execute()` treated any SQL-stage failure as fatal for the whole plan: on failure it skipped every remaining step in declaration order, not just the ones that actually depended on SQL.
- `AnswerAssemblyVerifier` required every answer to carry non-empty `sql_text` and `table_result.columns` — there was no alternate, evidence-only path to a valid answer.

**Promotion side:**
- `KnowledgePromotionService.promote_file()` reads already-chunked, already-embedded text from `FileVectorSource` (an interface; `InMemoryFileVectorSink` is the implementation wired into `create_app()`) and copies it into the durable knowledge store (`InMemoryKnowledgeStore` + `knowledge.*` Postgres tables). That cache is populated once, by `FileProcessingWorker`, when the file is first uploaded and processed — and it is in-process memory, so it does not survive a backend restart.
- `promote_file()` had no check for the case where `chunks_with_vectors_for_file(file_id)` returns nothing. It still created the `knowledge.documents` row and the (empty) `promoted_to_doc_id` link — a document that exists everywhere except in the one table (`knowledge.doc_chunks`) that RAG retrieval actually reads from.

## 3. Design: Splitting "Needs SQL" from "Needs RAG"

`QuestionClassifier` now derives whether a question needs SQL data at all, instead of assuming it always does:

```python
has_data_signal = _contains_any(question, DATA_DOMAIN_KEYWORDS)   # revenue, order, ticket, total, count, ...
is_chart = _contains_any(question, CHART_KEYWORDS)
is_analytics = _contains_any(question, ANALYTICS_KEYWORDS)
is_rag = _contains_any(question, RAG_KEYWORDS)                    # why, explain, document, ...

needs_sql = has_data_signal or is_chart or is_analytics or not is_rag
```

The last clause — `not is_rag` — is the important one: it means SQL stays the *default* for anything that isn't clearly a RAG question, so existing behavior for plain data questions ("What is revenue by month?") and combined questions ("Why did revenue drop?" — RAG match **and** a data-domain keyword) is unchanged. SQL is only dropped when a question matches a RAG keyword and nothing else — a document-only question like the Nimbus pricing example.

## 4. Design: The Plan Builder Skips the SQL Step When It Isn't Needed

`ExecutionPlanBuilder.build()` now includes the SQL step, and passes `depends_on=(AgentName.SQL,)` to every fanout step, only when `TaskType.SQL_QUERY` is in the classified set:

```python
needs_sql = TaskType.SQL_QUERY in task_types
sql_steps = (AgentPlanStep(AgentName.SQL, ExecutionStage.SQL),) if needs_sql else ()
sql_dependency = (AgentName.SQL,) if needs_sql else ()
# every fanout step now takes depends_on=sql_dependency instead of a hardcoded (AgentName.SQL,)
```

For a RAG-only plan this produces `(RAG, VERIFIER)` with no SQL step at all — `AgentName.RAG`'s `depends_on` is `()`, so `PlanExecutor` runs it immediately with no prerequisite to wait on. `simple_orchestrator.py` mirrors this: it classifies the question *before* deciding whether to call the LLM for SQL generation at all, and skips that call entirely when `needs_sql` is false — so a document-only question no longer pays for, or can be denied by, a SQL call it never needed.

`PlanExecutor.execute()` itself needed no change: its per-step dependency check (`if any(dep not in completed_agents for dep in step.depends_on)`) already gates correctly on whatever `depends_on` a step declares. The bug was entirely in what the plan builder handed it, not in how the executor interpreted it.

## 5. Design: Answer Verification Accepts Evidence-Only Grounding

`AnswerAssemblyVerifier._findings()` required `sql_text` and `table_result.columns` unconditionally. A document-only answer has neither — it is grounded in `evidence_list` instead. The check is now conditional:

```python
if not answer.evidence_list:
    if not answer.sql_text.strip():
        findings.append("sql_text is required.")
    if not answer.table_result.columns:
        findings.append("table_result.columns is required.")
```

A SQL-grounded answer (`evidence_list` empty, as before) is checked exactly as before — this preserves existing verifier tests unchanged. An evidence-grounded answer skips the SQL-shaped checks entirely. An answer with **neither** SQL output nor evidence still fails verification and gets capped at 0.5 confidence — this is deliberately still an error case, not silently accepted.

`AnswerAssemblyVerifier` is not the only place this assumption lived. `VerifierAgentRunner` — the agent-level verifier step that runs *inside* the plan, before final assembly — independently flags `"SQL text is missing."` whenever it is constructed with a non-`None`, blank `sql_text`. `_build_runners()` was passing `sql_text=sql_candidate`, and `sql_candidate` is `""` (not `None`) for a document-only question, so this second verifier failed the plan for the exact same reason the first one did, via a different code path. The fix is a one-line call-site change: `sql_text=sql_candidate or None` — `None` means "not applicable," a blank string means "missing," and only the latter is a finding. Caught by writing `TC-FV10-159` (an orchestrator-level test asserting `answer.warnings == ()` for a document-only question) before this call site was fixed — the test failed against the change described above alone, which is exactly what a design doc's "keep this in sync with the code" claim is supposed to guard against.

A third instance surfaced only through a live HTTP round-trip against the running Docker stack, after the first two were already fixed and tested: `RuntimeQueryResultRecord` (`src/chatbi/history/query_results.py`), the record persisted so `GET /api/v2/query-results/{trace_id}` can replay a past SQL result, has a `__post_init__` that raises `ValueError("sql_text is required")` for an empty `sql_text`. `runtime_query_result_record_from_response()` (`http.py`) already had a "nothing to persist" convention — `if not isinstance(sql_text, str): return None` — for a response with no `sql_text` field at all, but an empty string still satisfies `isinstance(..., str)`, so it fell through to constructing the record anyway, and the unhandled `ValueError` surfaced as a bare `500 INTERNAL_ERROR` on `/api/v2/chat/query` — the one place in this whole chain where the bug was not "wrong answer" but "no answer at all." The fix extends the existing convention: `if not isinstance(sql_text, str) or not sql_text.strip(): return None`. This record has no `evidence_list`-shaped alternative grounding to fall back to (unlike `QueryAnswer`) — it exists specifically to replay a SQL result, so "there is no SQL result to persist" is correctly represented by skipping the record entirely, not by relaxing its validation.

Three independent places assumed "every answer has SQL text," found one at a time by three different kinds of test: a unit test on the verifier, an orchestrator-level test that exercises the full answer-assembly path, and — for the one unit/orchestrator-level tests could not reach, because it lives in HTTP response serialization, not in `QueryAnswer` construction — an actual HTTP request against a running server. This is the concrete case for §7's limitation note applying equally here: fixing "the" bug is rarely fixing all of it when an invariant was assumed in more than one place.

## 6. Design: Promotion Fails Loudly Instead of Creating Dead Documents

`KnowledgePromotionService.promote_file()` now checks `chunks_with_vectors_for_file()` before doing anything else:

```python
chunks_with_vectors = self._vector_source.chunks_with_vectors_for_file(file_id)
if not chunks_with_vectors:
    raise FileNotPromotableError(file_id)
```

This turns a silent, permanent data-integrity problem (a document that will never be found by any query, forever, with nothing in the API response to say so) into an immediate, actionable `422 FILE_NOT_PROMOTABLE` at the moment of the mistake. The caller's correct recovery — confirmed by testing — is to re-upload the file, which re-runs `FileProcessingWorker` in the *current* process and repopulates the vector source, after which promotion succeeds and the document is genuinely retrievable.

## 7. Known Limitation — Not Fixed Here

The underlying cause is still present: `FileVectorSource` (`InMemoryFileVectorSink`) is process-local and never persisted, so a file's chunked-and-embedded content is only ever available for promotion within the same process lifetime that processed it. §6 turns that into a clear error instead of silent corruption, but does not remove the constraint itself. A durable fix — backing `FileVectorSource` with Postgres, or re-deriving chunks on demand from the durably-stored original file bytes at promotion time — is a larger change and is out of scope here.

## 8. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-057 | `QuestionClassifier` must classify a question as needing SQL only when it matches a data-domain, chart, or analytics signal, or matches no RAG signal at all; a RAG-only match with no such signal must not include `TaskType.SQL_QUERY`. | Implemented |
| FR-FV10-058 | `ExecutionPlanBuilder` must omit the SQL step, and must not set any fanout step's dependency to `AgentName.SQL`, when `TaskType.SQL_QUERY` is absent from the classified set. | Implemented |
| FR-FV10-059 | The orchestrator must not call the SQL-generation LLM request when the classified task types do not include `TaskType.SQL_QUERY`. | Implemented |
| FR-FV10-060 | `AnswerAssemblyVerifier` must accept an answer with empty `sql_text`/`table_result` as valid when `evidence_list` is non-empty, and must still reject an answer with neither. | Implemented |
| FR-FV10-061 | `KnowledgePromotionService.promote_file()` must raise `FileNotPromotableError` instead of creating a knowledge document when the file's vector source has no chunks to copy. | Implemented |
| FR-FV10-062 | `VerifierAgentRunner` must not report a missing-SQL finding when no SQL step was planned for the question; the orchestrator must pass `sql_text=None` (not an empty string) to it in that case. | Implemented |
| FR-FV10-063 | `runtime_query_result_record_from_response()` must return `None`, not construct `RuntimeQueryResultRecord`, when the response's `sql_text` is an empty or whitespace-only string. | Implemented |
| NFR-FV10-021 | The RAG-only routing change must not alter existing behavior for questions that classify as needing both SQL and RAG (e.g. "Why did revenue drop?"), or SQL-only/chart/analytics questions. | Verified by regression tests |
