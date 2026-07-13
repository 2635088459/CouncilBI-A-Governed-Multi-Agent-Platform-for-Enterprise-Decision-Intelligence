# 10.6 Hybrid File Answering for Mixed Structured/Unstructured Selections

## 1. Problem Solved

[10.5](05-rag-only-routing-and-promotion-durability.en.md) §6 fixed `FileDataAgent`/`FederatedQueryAgent` so that selecting an unstructured file (PDF/DOCX/TXT/MD/PPTX) alongside — or instead of — a structured one no longer crashes: the unstructured file is filtered out before SQL generation, and a clear `NO_STRUCTURED_FILE_SELECTED` error is returned when nothing structured remains to query. That fix is deliberately conservative: it stops the crash but never actually answers from the unstructured file's content. A user who attaches a CSV and a PDF and asks a question gets an answer from the CSV alone, with no indication the PDF was silently dropped, or an outright error if they attached only the PDF.

This document designs the next step: when unstructured files are attached, retrieve evidence from their own content and synthesize one answer that draws on structured query results and unstructured evidence together, exactly as the main orchestrator already does for a "why did revenue drop" question (SQL rows + knowledge-base RAG evidence in one answer).

## 2. What Already Exists

Three pieces needed for this are already in the codebase, built for other purposes:

- **`FileVectorSource.chunks_with_vectors_for_file(file_id)`** (`src/chatbi/files/worker.py`) — already-chunked, already-embedded text for one file, keyed by `file_id`. `FileProcessingWorker` populates it at upload time; `KnowledgePromotionService.promote_file()` (10.5 §6) already reads from it to copy a file's content into the shared knowledge base. This design reuses the same read, for a different purpose: searching one request's attached files directly, with no promotion step.
- **`GroundedAnswerSynthesizer.synthesize(question, safe_sql, table_result, evidence_list, ...)`** (`src/chatbi/answer_synthesis.py`) — already accepts both a SQL result set and an evidence list in the same call; this is exactly what the main orchestrator uses for a combined SQL+RAG answer today. Producing both a `table_result` and an `evidence_list` in the file-handling branch and passing both here requires no change to this function.
- **`AnswerAssemblyVerifier`** (10.5 §5) — already accepts an answer with empty `sql_text`/`table_result` as valid when `evidence_list` is non-empty. An unstructured-file-only answer (no structured file attached at all) already passes final verification without modification.
- **The parent spec already specified this and it was never built**: [Spec FV-10 §4](../../../../spec/final-version/en/10-user-file-upload-and-hybrid-analysis.spec.en.md) FR-FV10-023 — "The RAG agent MUST apply a `user_id + file_id` scope filter when retrieving vector chunks from user-uploaded unstructured files." That requirement describes exactly this feature — retrieval scoped to the requesting user's own attached files, not the org-wide promoted knowledge base — and FR-FV10-025 already specifies a `📎 Uploaded` evidence-card label distinct from knowledge-base evidence. Neither was wired into `_handle_file_data_chat_query`; this document is the design for actually building them.

## 3. Design: Split `file_ids` by Type Before Deciding How to Answer

`_handle_file_data_chat_query` (`http.py`) currently makes a binary choice: `FederatedQueryAgent` if the question also names a resolvable business table, else `FileDataAgent` — both exclusively SQL-over-structured-files. It now splits `file_ids` first:

```python
structured_ids, unstructured_ids = split_file_ids_by_type(file_ids, file_repository)
```

`structured_ids` (possibly empty) continues down the existing SQL path unchanged. `unstructured_ids` (possibly empty) is new: it feeds the retriever in §4. Either set can be empty; both being empty is unreachable (FR-FV10-020's `_validate_chat_query_file_ids` already rejects an empty `file_ids` before this handler is reached).

## 4. Design: `FileScopedRetriever` — the Knowledge Store's Ranking Logic Over a Narrower Candidate Set

A new, small class, not a new ranking algorithm:

```python
class FileScopedRetriever:
    """FR-FV10-023: RAG evidence scoped to exactly this request's file_ids,
    not the org-wide promoted knowledge base. No promotion step, no admin
    approval — the files are already the requesting user's own, already
    ownership-checked before this handler is reached."""

    def __init__(self, vector_source: FileVectorSource) -> None:
        self._vector_source = vector_source

    def retrieve(
        self, *, question: str, file_ids: tuple[str, ...], top_k: int = 5
    ) -> tuple[EvidenceItem, ...]:
        candidates = tuple(
            (file_id, chunk, vector)
            for file_id in file_ids
            for chunk, vector in self._vector_source.chunks_with_vectors_for_file(file_id)
        )
        ranked = _rank_by_relevance(question, candidates)  # reuses knowledge.py's scoring
        return tuple(_evidence_item_from_chunk(file_id, chunk) for file_id, chunk, _ in ranked[:top_k])
```

The ranking itself — keyword overlap + cosine similarity over `text_embedding()` — is not reinvented: `InMemoryKnowledgeStore._rank_records`/`_keyword_score`/`_cosine_similarity` (`knowledge.py`) already do this correctly (verified today, 10.5's Nimbus-pricing retrieval test) against a candidate set drawn from the *promoted* knowledge base. `FileScopedRetriever` calls the same scoring functions against a candidate set drawn from `chunks_with_vectors_for_file()` instead — a deliberately narrow, cheap, per-request lookup, not a second knowledge store.

## 5. Design: Merge Both Branches Into One Synthesized Answer

```python
table_result = run_structured_query(structured_ids, question) if structured_ids else None
evidence_list = file_scoped_retriever.retrieve(question=question, file_ids=unstructured_ids) if unstructured_ids else ()

if table_result is None and not evidence_list:
    return error_envelope(code=ApiErrorCode.REQ_INVALID_ARGUMENT, message="...")

answer = answer_synthesizer.synthesize(
    question=question,
    safe_sql=sql_text or "",
    table_result=table_result or TableResult(columns=(), rows=()),
    evidence_list=evidence_list,
    ...
)
```

The failure case from 10.5 §6 (`NO_STRUCTURED_FILE_SELECTED`) becomes a special case of a more general rule: the request fails only when **neither** branch produced anything, not whenever a structured file is absent. Attaching only a PDF and asking a question the PDF actually answers now succeeds — it did not before this design, regardless of content.

## 6. Design: Evidence Provenance — `📎 Uploaded` vs. Knowledge-Base Evidence

FR-FV10-025 (parent spec) already specifies this distinction; it was never implemented because nothing produced request-scoped file evidence to distinguish. `EvidenceItem`s from `FileScopedRetriever` carry a marker (e.g. `source_id` prefixed `ufile_` — the file's own ID, distinct from the `doc_` prefix every promoted knowledge-base document already uses) that the frontend's `EvidenceSection` reads to render a `📎 Uploaded` badge instead of the plain source title used for knowledge-base evidence. No new field is required on `EvidenceItem` — the existing `source_id` naming convention already carries this distinction; the frontend just needs to branch on the prefix, the same way it already branches on `table_result_source === "file"` for the `📎 File data` badge.

## 7. Known Limitation — Inherits 10.5's Durability Gap

`FileScopedRetriever` reads from the same `FileVectorSource` whose in-process-only, restart-losing nature 10.5 §7 already documents and left unfixed. A `ready` unstructured file whose chunks were produced in a prior process lifetime will return an empty candidate set here, exactly as it does for promotion. Per 10.5's pattern (fail loudly, don't silently under-deliver): if `chunks_with_vectors_for_file(file_id)` returns empty for every requested unstructured file, this design surfaces that as a distinct condition (e.g. `FILE_CONTENT_UNAVAILABLE`) rather than an empty `evidence_list` indistinguishable from "the document doesn't mention this" — the same failure mode 10.5 fixed for promotion, recurring here because it is the same underlying data source, and this document does not fix the underlying durability gap either.

## 8. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-064 | `_handle_file_data_chat_query` MUST split `file_ids` into a structured subset and an unstructured subset before deciding how to answer, using each file's `file_type`/`schema_json` as recorded in the file repository. | Implemented — see spec |
| FR-FV10-065 | When the unstructured subset is non-empty, the system MUST retrieve evidence via a retriever scoped to exactly those `file_ids`, drawn from `FileVectorSource.chunks_with_vectors_for_file()`, not from the org-wide promoted knowledge base. | Implemented — see spec |
| FR-FV10-066 | The final answer MUST be synthesized from whichever of `table_result` (structured subset) and `evidence_list` (unstructured subset) are non-empty; the request MUST fail only when both are empty. | Implemented — see spec |
| FR-FV10-067 | An `EvidenceItem` sourced from a request-scoped uploaded file MUST be distinguishable from knowledge-base evidence (e.g. by `source_id` prefix), and the frontend MUST render it with a `📎 Uploaded` label distinct from knowledge-base evidence cards, per parent spec FR-FV10-025. | Implemented — see spec |
| FR-FV10-068 | The retriever in FR-FV10-065 MUST NOT retrieve chunks for a `file_id` the requesting user does not own — reusing the ownership check `_validate_chat_query_file_ids` already performs before this handler is reached, not a new authorization mechanism. | Implemented — see spec |
| FR-FV10-069 | If `chunks_with_vectors_for_file()` returns empty for every requested unstructured file, the system MUST surface a distinct "content not available for search" condition, not an empty `evidence_list` that reads as "the document doesn't mention this." | Implemented — see spec |
| NFR-FV10-022 | This design MUST NOT alter existing behavior for a request whose `file_ids` are entirely structured (pure SQL path, unchanged) or entirely absent (main orchestrator path, unchanged). | Implemented — see spec |

## 9. Status: Implemented

Per this project's SDD+TDD convention, [Spec FV10.6](../../../../spec/final-version/en/10-followups/06-hybrid-file-answering-for-mixed-selections.spec.en.md) turned this design into acceptance criteria, test cases, and a traceability matrix, and the implementation is complete and tested. The spec is the authoritative, up-to-date source for exact requirement wording — implementation surfaced two refinements this design doc predates and does not reflect:

- An additional requirement (FR-FV10-070 in the spec) for the partial-availability case — some requested unstructured files return chunks, others don't — which this design's §7 durability discussion didn't separately call out.
- §6's evidence-labeling mechanism (FR-FV10-067/068 here) turned out to already exist: `ResultMerger.merge()` already had an `uploaded_file_evidence` parameter and an `is_uploaded_file`-tagged title-prefixing mechanism, built for this exact purpose and simply never fed anything. The spec's §6.3 documents this — no new frontend code was needed, unlike what this design's §6 implied.
