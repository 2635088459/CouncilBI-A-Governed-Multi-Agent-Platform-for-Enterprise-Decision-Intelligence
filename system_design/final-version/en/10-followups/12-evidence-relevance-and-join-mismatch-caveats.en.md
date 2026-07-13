# 10.12 Evidence Relevance Gating and Join-Mismatch Caveats for Hybrid File/Warehouse Comparison Answers

中文版：[../../zh-CN/10-followups/12-evidence-relevance-and-join-mismatch-caveats.zh-CN.md](../../zh-CN/10-followups/12-evidence-relevance-and-join-mismatch-caveats.zh-CN.md)

## 1. Problem Observed

An analyst attached `regional_sales_h1_2026.csv` (columns `region`, `month`, `revenue`, `orders`) and asked: *"I've uploaded our internal regional sales file for H1 2026. Compare it against the revenue numbers in the data warehouse for the same period and flag any regions with more than 5% variance."*

The response had two independent problems:

1. **The answer text asserted a conclusion the system never verified.** It said "the SQL query executed... returned no results, indicating that there were no regions with more than 5% variance." A zero-row result from a `JOIN` between the uploaded file and the warehouse table is also exactly what a **join-key mismatch** produces — e.g. `"US-West"` in the file vs. `"us-west"` or `"West"` in the warehouse, or a `month` format mismatch. Nothing in the pipeline distinguishes "we compared every region and none exceeded 5%" from "we matched nothing at all," yet the answer confidently asserted the former.
2. **The "Sources" panel displayed two documents with no connection to the question**: "July 2026 Revenue Drop — Campaign Pause Root Cause Analysis" and "2025 Holiday Season Revenue and Support Surge — Post-Mortem." Neither document discusses regional sales variance, the uploaded file, or anything the answer text actually used. They were retrieved and displayed anyway.

Both defects were reproduced by reading the exact code path this question takes — `_handle_file_data_chat_query()` in `src/chatbi/api/http.py` — rather than a live LLM replay, since both root causes are structural (present regardless of what any specific LLM call returns) rather than a one-off model mistake.

## 2. What Already Exists

### 2.1 Why an unrelated knowledge-base search ran at all

`_handle_file_data_chat_query()` classifies the question with the same general-purpose `QuestionClassifier.classify()` used everywhere else (`src/chatbi/orchestration/routing.py:97-125`), unaware that this call site is answering a file/warehouse comparison, not a "why did X happen" document question:

```python
task_types = question_classifier.classify(question)
```

`QuestionClassifier._RAG_KEYWORDS` (`routing.py:61-65`) includes the bare word `"internal"`:

```python
_RAG_KEYWORDS = (
    "why", "reason", "cause", "explain", "what happened",
    "incident", "report", "document", "context", "background",
    "according to", "internal", "analysis says", "review",
)
```

The reported question contains "our **internal** regional sales file" — one ordinary word an analyst would use for "our own, not a vendor's, data" — and that alone adds `TaskType.RAG_EXPLANATION` to the classification result. `_RAG_KEYWORDS` also contains `"report"` and `"review"`, both plausible in an analyst's everyday phrasing of a file-comparison question ("compare this report," "review the variance"), so this is not a one-word coincidence; it is a structural mismatch between a keyword list built for document-explanation questions and a call site that also has to handle comparison questions phrased in ordinary business language.

### 2.2 Why the retrieved documents were shown regardless of relevance

Once `TaskType.RAG_EXPLANATION` is present, `http.py:2554-2570` runs an org-wide semantic search with no awareness of the file-comparison context:

```python
if TaskType.RAG_EXPLANATION in task_types and active_knowledge_store is not None:
    retrieval_result = active_knowledge_store.retrieve(
        RetrievalQuery(
            question=question,
            requesting_user_id=user_id,
            user_role=role,
            top_k=5,
            conversation_context=" ".join(
                message["content"] for message in conversation_context
            ),
        ),
        trace_id=trace_id,
    )
    knowledge_base_evidence = tuple(
        EvidenceItem(..., relevance_score=item.relevance_score)
        for item in retrieval_result.evidence_list
    )
```

`InMemoryKnowledgeStore.retrieve()` (`src/chatbi/knowledge.py:280-295`) ranks by a blended score and keeps the top `top_k`, but its only floor is `relevance_score <= 0` (`knowledge.py:363`) — anything with the faintest keyword or vector overlap clears that bar. For a five-document knowledge base, `top_k=5` can return the entire base, ranked but unfiltered by any meaningful cutoff.

That `knowledge_base_evidence` tuple is passed straight into `ResultMerger.merge()` (`src/chatbi/orchestration/result_merger.py:53-64`), whose own docstring (`result_merger.py:1-19`) states plainly: *"This module does not execute SQL, call an LLM, or narrate anything itself — it only shapes whichever agent outputs already ran into one tagged context."* `_tag_evidence()` (`result_merger.py:111-121`) confirms this — it concatenates `uploaded_file_evidence` and `knowledge_base_evidence` unconditionally, with no relevance-score parameter at all:

```python
def _tag_evidence(
    self,
    uploaded_file_evidence: tuple[EvidenceItem, ...],
    knowledge_base_evidence: tuple[EvidenceItem, ...],
) -> tuple[SourcedEvidenceItem, ...]:
    return tuple(
        SourcedEvidenceItem(evidence=item, is_uploaded_file=True) for item in uploaded_file_evidence
    ) + tuple(
        SourcedEvidenceItem(evidence=item, is_uploaded_file=False)
        for item in knowledge_base_evidence
    )
```

`evidence_payload` (`http.py:2604-2616`) renders every item in `merged.evidence_items` into the API response's "Sources" list, unconditionally. Nothing in this chain ever checks whether the final synthesized answer text actually used a given piece of evidence — `ResultMerger` runs before answer synthesis, not after, by design (§2's docstring again: it only *shapes context*, it does not narrate). Low-relevance, unrelated evidence is guaranteed to reach the UI once `TaskType.RAG_EXPLANATION` fires at all.

### 2.3 Why a zero-row join result was narrated as "no variance"

`FederatedQueryAgent.run()` (`src/chatbi/agents/federated_query_agent.py:138-206`) materializes the warehouse rows as `db_{table}` and the file as `file_{file_id}` (`_register_views`, lines 164-171), asks the LLM for one JOIN/comparison SQL statement (`_generate_sql`, lines 261-300), executes it, and returns whatever DuckDB produces:

```python
try:
    columns, rows = fetch_table(connection, sql_text)
except QueryResourceExceededError:
    ...
except InvalidGeneratedSqlError:
    ...
return FederatedQueryAgentOutput(
    degraded=False,
    table_result=TableResult(columns=columns, rows=rows),
    federated_sql=sql_text,
)
```

There is no comparison anywhere in this method between the row counts of the two source views and the row count of the final result. A `JOIN ... ON f.region = d.region` where the file stores `"US-West"` and the warehouse stores a different spelling produces a syntactically and semantically valid query that returns zero rows — indistinguishable, at this layer, from "every region really was compared and none exceeded 5%." The downstream answer-synthesis LLM call (`src/chatbi/answer_synthesis.py`) is handed the same empty `TableResult` in both cases and has no signal telling it these are different situations, so it free-hands whichever explanation reads more naturally for a table with zero rows — in the reported case, "no variance."

## 3. Design: A Relevance-Score Floor at the Point Evidence Is Rendered

Rather than trying to perfect `_RAG_KEYWORDS` — any fixed English keyword list will eventually contain a word an analyst uses for an unrelated reason, the same lesson [10.8](08-question-relevance-gate-before-file-branch-routing.en.md) and [10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.en.md) already drew for the *file-routing* gate — this fixes the *symptom that actually reached the user*: evidence with no real bearing on the answer must not be rendered as if it were a source for it, independent of why retrieval was triggered.

A minimum relevance-score floor is applied to `knowledge_base_evidence` at the point `_handle_file_data_chat_query()` turns retrieval results into `EvidenceItem`s (`http.py:2571-2580`), before it ever reaches `ResultMerger`:

```python
_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE = 0.15  # value corrected during implementation — see §9

knowledge_base_evidence = tuple(
    EvidenceItem(..., relevance_score=item.relevance_score)
    for item in retrieval_result.evidence_list
    if item.relevance_score >= _MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE
)
```

This is deliberately scoped to the hybrid file-comparison path only (`_handle_file_data_chat_query`), the call site the reported answer actually took — it does not change the main orchestrator's own, separately-triggered RAG behavior. `uploaded_file_evidence` (from `FileScopedRetriever`, scoped to the user's own attached unstructured files) is unaffected: unlike an org-wide knowledge-base search, evidence retrieved from a file the user explicitly attached to *this* request is relevant by construction, the same reasoning [10.8 §4](08-question-relevance-gate-before-file-branch-routing.en.md#4-design-wiring-the-gate-into-the-routing-decision) already applies to unstructured files.

This does not touch `_RAG_KEYWORDS` or `QuestionClassifier` at all — a hybrid comparison question that happens to contain "internal" still triggers a knowledge-base search, but a search that finds nothing genuinely relevant now correctly returns no sources instead of padding the response with the nearest-ranked unrelated documents.

## 4. Design: A Row-Count Caveat When a Join Produces Zero Rows

`FederatedQueryAgentOutput` gains one new field, populated by `FederatedQueryAgent.run()` immediately after materializing the source views and before generating SQL:

```python
@dataclass(frozen=True, slots=True)
class FederatedQueryAgentOutput:
    ...
    zero_row_join_caveat: bool = False
```

Computed as: the final query returned zero rows, the generated SQL text contains a `JOIN` keyword (case-insensitive), and both source views (`db_{table}`, `file_{file_id}`) had at least one row before the join ran. The third condition matters: if either source itself was empty, an empty result is the *correct*, unambiguous answer ("your file has no rows for this period") — the caveat exists specifically for the case a naive reading of "zero rows" would misinterpret, not for every empty result.

When `zero_row_join_caveat` is `True`, `_handle_file_data_chat_query()` passes an explicit instruction into the answer-synthesis prompt (`answer_synthesis.py`) rather than leaving the LLM to free-hand an explanation for an empty table:

> The comparison query matched zero rows across the join, even though both the file and the warehouse table each had data for this period. State plainly that no matching records were found across the join key(s) — do not claim this means all values are within any threshold, since a join-key mismatch (e.g. differing spelling, capitalization, or date format between the file and the warehouse column) produces the identical zero-row result. Recommend the user verify that the shared column(s) use the same values/format in both sources.

This turns a previously indistinguishable code path into two observably different answers: a real "no variance found" narrative when the join actually matched rows and none exceeded the threshold, and an explicit "nothing matched" caveat when it did not match at all.

## 5. Verification

Per this project's SDD+TDD convention, [Spec FV10.12](../../../../spec/final-version/en/10-followups/12-evidence-relevance-and-join-mismatch-caveats.spec.en.md) turned §3 and §4 above into functional requirements, acceptance criteria, and test cases before implementation. In outline:

- Unit tests for the relevance-score floor (`tests/test_chat_query_with_files.py`): a fake knowledge store returning `relevance_score` values `[0.9, 0.4, 0.1]` produces `knowledge_base_evidence` containing only the items at or above the floor; `uploaded_file_evidence` is unaffected by the same fixture.
- Unit tests for `FederatedQueryAgent` (`tests/test_federated_query_agent.py`): a fake LLM client returning a `JOIN`-containing SQL statement against two non-empty, non-matching source views sets `zero_row_join_caveat=True`; the same fixture with matching join keys and a non-empty result sets it `False`; an empty *source* view, and a query with no `JOIN` keyword at all, both also set it `False`.
- HTTP-level tests (`tests/test_chat_query_with_files.py`, `tests/test_chat_query_federated.py`) covering the relevance floor and the join-mismatch caveat end to end, including one confirming the caveat instruction actually reaches the answer-synthesis prompt.

See §9 for a correction to the relevance floor's exact value, made while writing the first of these tests, before any of it was run against real code.

## 6. Known Limitations — Intentionally Not Addressed Here

- **The relevance floor is a fixed constant, not adaptive, and — per §9's finding — a weak signal in this store's current scoring algorithm specifically.** `InMemoryKnowledgeStore`'s keyword+hashed-embedding scoring rewards a document's vocabulary breadth more than its topical relevance: measured during implementation, a short, precisely on-topic snippet scored 0.2267, while reconstructions of the *originally reported bug's own unrelated documents* scored 0.3502 and 0.4011 for the same question. No single floor value can keep the first and exclude the other two — §9 recounts choosing 0.15 to protect the former at the cost of no longer reliably excluding the latter. This is a materially worse gap than the "principled threshold, not a semantic judgment" framing this section originally used, and than the analogous limitation [10.8 §6](08-question-relevance-gate-before-file-branch-routing.en.md#6-known-limitations--not-fixed-here) documented for the token-overlap relevance gate — there, a false negative degrades gracefully to the main orchestrator; here, the floor may simply not fire on the exact case that motivated it.
- **The join-mismatch caveat only fires for a fully empty result.** A join that matches *some* rows correctly and silently drops others (e.g. three of five regions match, two don't) produces a non-empty, plausible-looking result with no caveat at all — a partial mismatch is a strictly harder problem than a total one and remains out of scope. (This bullet originally also listed "only fires for a literal `JOIN` keyword" as a limitation — closed by [10.14](14-comparison-query-detection-beyond-literal-join.en.md) after a live re-test of this exact scenario reproduced the bug through an `EXCEPT`-based comparison query.)
- **`_RAG_KEYWORDS` itself is untouched.** This design fixes what gets *shown*, not what gets *searched for* — the underlying over-broad trigger condition ("internal," "report," "review") remains, and will keep causing unnecessary knowledge-base searches on hybrid file-comparison questions. Given §9's finding, that search is *not* reliably harmless to the user the way §3 originally assumed — a future followup should treat narrowing or corroborating `_RAG_KEYWORDS` itself (the same corroboration-signal approach [10.9](09-data-domain-signal-safety-net-for-the-relevance-gate.en.md) used for the file-routing gate) as the higher-priority fix, not an optional one.

## 7. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-084 | In `_handle_file_data_chat_query()`, `knowledge_base_evidence` items with `relevance_score` below a fixed minimum floor MUST be excluded before being passed to `ResultMerger.merge()`. | Implemented |
| FR-FV10-085 | `FederatedQueryAgentOutput` MUST expose a `zero_row_join_caveat: bool` field, `True` only when the final result has zero rows, the generated SQL contains a `JOIN` keyword, and both source views had at least one row before the join ran. | Implemented |
| FR-FV10-086 | When `zero_row_join_caveat` is `True`, the answer-synthesis prompt MUST receive an explicit instruction not to characterize the result as confirming a threshold comparison, and to state that no matching rows were found across the join key(s). | Implemented |
| NFR-FV10-029 | This spec's relevance floor MUST NOT alter `uploaded_file_evidence` (evidence scoped to the user's own attached unstructured files via `FileScopedRetriever`) — only `knowledge_base_evidence` from the org-wide search is filtered. | Implemented |

## 8. Status: Fixed and Verified — With a Corrected Threshold

Found via direct code-path reading of the exact call site (`_handle_file_data_chat_query`) the reported answer took, not a live LLM replay — both root causes are structural and reproduce for any question that shares their trigger conditions, independent of model output. Written spec-first, per this project's usual SDD+TDD order: [Spec FV10.12](../../../../spec/final-version/en/10-followups/12-evidence-relevance-and-join-mismatch-caveats.spec.en.md) formalized §3 and §4 above into requirements, acceptance criteria, and a test plan, then both were implemented. Fixed in `src/chatbi/api/http.py`, `src/chatbi/files/contracts.py`, `src/chatbi/agents/federated_query_agent.py`, and `src/chatbi/answer_synthesis.py`; covered by new tests in `tests/test_chat_query_with_files.py`, `tests/test_chat_query_federated.py`, `tests/test_federated_query_agent.py`, and `tests/test_answer_synthesis.py`. The full project test suite (1396 tests, excluding the pre-existing Postgres-credential and frontend-bundle failures this project's own convention already documents as unrelated) passes. §9 records a correction to the relevance floor's value made while building its first test fixture, before that fixture was run against any production code.

## 9. A Correction Found While Writing the Relevance Floor's First Test

§3's original value, `0.35`, was chosen without measuring it against `InMemoryKnowledgeStore`'s actual scoring behavior. Writing `tests/test_chat_query_file_rag_analytics.py`'s pre-existing regression fixture against the implemented floor — a real "why did revenue change" question against a document reading "Revenue dropped in March because a marketing campaign was paused for three weeks" — surfaced that this store's `retrieve()` scores that pairing at **0.2267**, below the proposed floor, which would have silently dropped evidence a pre-existing test already asserts is returned.

Reconstructing the *originally reported bug's own two unrelated documents* (a July revenue-drop root-cause doc and a 2025 holiday-season post-mortem) against the exact reported question found they score **0.3502** and **0.4011** — both *above* `0.35`. A completely unrelated support-ticket document, tested for comparison, scored **0.3548**. The reason: `InMemoryKnowledgeStore`'s `relevance_score` (`knowledge.py:362`, `keyword_score * 0.60 + vector_score * 0.35 + source_score`) rewards a document's total vocabulary — longer documents accumulate more incidental keyword and hashed-embedding-bucket overlap with almost any query — more than it rewards genuine topical relevance. A short, precisely on-topic snippet can score *lower* than a long, generically related but off-topic one.

No single floor value satisfies both constraints (0.2267 < 0.3502 < 0.4011). `_MIN_KNOWLEDGE_BASE_RELEVANCE_SCORE` was set to `0.15` — below the passing regression test's score, preserving existing behavior, while still excluding near-zero, essentially coincidental matches. This is not the design originally described in §3: it is a floor calibrated to avoid a regression, not one shown to solve the motivating bug. §6 above is corrected accordingly, and §8's "Fixed and Verified" should be read against that narrower claim — the *Sources-pollution symptom* (irrelevant chunks rendered as citations) is fixed for genuinely low-scoring noise; a reconstruction of the exact originally reported documents is not reliably excluded by this fix alone.
