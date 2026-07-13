# Spec FV10.6: Hybrid File Answering for Mixed Structured/Unstructured Selections

Source design:
- [10.6 Hybrid File Answering for Mixed Structured/Unstructured Selections design](../../../../system_design/final-version/en/10-followups/06-hybrid-file-answering-for-mixed-selections.en.md)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (parent spec; this spec finally implements its FR-FV10-023 and FR-FV10-025, left unbuilt since the parent spec was written)
- [Spec FV10.5: RAG-Only Routing and Knowledge Promotion Durability](05-rag-only-routing-and-promotion-durability.spec.en.md) (this spec supersedes 10.5's `NO_STRUCTURED_FILE_SELECTED` failure case with a narrower one — see §4 FR-FV10-066 — and reuses its `FileDataAgent`/`FederatedQueryAgent` structured/unstructured split from FR-FV10-057/058 of that spec unchanged)

---

## 1. Purpose

Spec FV10.5 stopped `FileDataAgent`/`FederatedQueryAgent` from crashing when an unstructured file (PDF/DOCX/TXT/MD/PPTX) is among the selected `file_ids`: the unstructured file is filtered out before SQL generation, and the request fails with a clear error when no structured file remains. That is deliberately a "don't crash" fix, not a "answer correctly" one — a question that an attached PDF could actually answer still fails, or silently ignores the PDF if a CSV was also attached.

This spec defines the next step: retrieving evidence from a request's own attached unstructured files, and merging it with any structured-file SQL results into one synthesized answer — the file-attached equivalent of what the main orchestrator already does for a "why did revenue drop?" question (SQL rows + knowledge-base RAG evidence together). This closes parent Spec FV-10's FR-FV10-023 (user-uploaded-file RAG scoping) and FR-FV10-025 (`📎 Uploaded` evidence labeling), both specified there and never implemented.

## 2. Scope

**In scope:**
- Splitting a chat query's `file_ids` into a structured subset and an unstructured subset before deciding how to answer.
- Retrieving evidence from the unstructured subset's own already-chunked-and-embedded content, scoped to exactly the requested `file_ids` — not the org-wide promoted knowledge base from Spec FV10.1.
- Synthesizing one answer from whichever of the structured subset's `table_result` and the unstructured subset's `evidence_list` are non-empty.
- Distinguishing evidence sourced from a request-scoped uploaded file from knowledge-base evidence, using the existing `is_uploaded_file` tagging and title-prefixing mechanism (§6.3) — not a new one.
- A distinct, non-silent condition for the case where every requested unstructured file's content is currently unavailable for search (the same in-process, restart-losing `FileVectorSource` limitation Spec FV10.5 §7 already documented).

**Out of scope:**
- Fixing the underlying `FileVectorSource` durability gap itself (Spec FV10.5 §7's "Known Limitation," inherited unchanged here — see §7).
- Any change to `InMemoryKnowledgeStore`'s ranking algorithm (`_rank_records`/`_keyword_score`/`_cosine_similarity`) — reused as-is against a different, narrower candidate set.
- Any change to `GroundedAnswerSynthesizer.synthesize()`'s signature — it already accepts both `table_result` and `evidence_list` in one call.
- Any change to `AnswerAssemblyVerifier` — Spec FV10.5 FR-FV10-060 already accepts an evidence-only-grounded answer.
- Promotion, sharing, or org-wide visibility of a request-scoped file's content (Spec FV10.1/FV10.2 govern that separately; this spec's retrieval is private to the requesting user's own already-ownership-checked files for the lifetime of one request).

## 3. Actors

Reuses the actors defined in the parent FV-10 spec §3. No new actor.

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-064 | `_handle_file_data_chat_query` MUST split the request's `file_ids` into a structured subset (`file_type == "structured"`, equivalently `schema_json is not None`) and an unstructured subset (`file_type == "unstructured"`) before deciding how to answer, using each file's repository record. |
| FR-FV10-065 | When the unstructured subset from FR-FV10-064 is non-empty, the system MUST retrieve evidence via a retriever scoped to exactly those `file_ids`, reading from `FileVectorSource.chunks_with_vectors_for_file()` for each one. This retrieval MUST NOT read from or write to the org-wide promoted knowledge base (`InMemoryKnowledgeStore` / `knowledge.*` Postgres tables) used by Spec FV10.1. |
| FR-FV10-066 | The final answer MUST be synthesized from whichever of the structured subset's `table_result` and the unstructured subset's `evidence_list` are non-empty. The request MUST fail with `NO_ANSWERABLE_FILE_SELECTED` only when the structured subset produced no `table_result` AND the unstructured subset produced an empty `evidence_list` for a reason other than FR-FV10-069. This supersedes Spec FV10.5 FR-FV10-061's `NO_STRUCTURED_FILE_SELECTED` failure, which now applies only when there is no unstructured evidence to fall back on either. |
| FR-FV10-067 | Every `EvidenceItem` produced by the retriever in FR-FV10-065 MUST be passed to `ResultMerger.merge()` via its `uploaded_file_evidence` parameter (not `knowledge_base_evidence`), so it is tagged `SourcedEvidenceItem(is_uploaded_file=True)` — the mechanism this codebase already uses to distinguish request-scoped file evidence from knowledge-base evidence (§6.3). Its `source_id` MUST still equal the originating file's own `file_id` (already `ufile_`-prefixed throughout this codebase) for traceability, but that prefix is not what the system uses to tell the two evidence kinds apart. |
| FR-FV10-068 | The response's `evidence_list` MUST render a `📎 ` prefix on the `title` of any evidence item tagged `is_uploaded_file=True`, distinct from the unprefixed `title` used for knowledge-base evidence — this MUST use the existing title-prefixing already present in `_handle_file_data_chat_query`'s evidence-payload construction; no new frontend rendering logic is needed or introduced by this spec. |
| FR-FV10-069 | The retriever in FR-FV10-065 MUST NOT retrieve chunks for any `file_id` that `_validate_chat_query_file_ids` has not already screened for the requesting `user_id`'s ownership and `ready` status — it MUST reuse that existing screening, not introduce a second authorization check. |
| FR-FV10-070 | If `FileVectorSource.chunks_with_vectors_for_file(file_id)` returns an empty tuple for every `file_id` in the unstructured subset, the system MUST return `FILE_CONTENT_UNAVAILABLE`, distinct from `NO_ANSWERABLE_FILE_SELECTED` (FR-FV10-066) and distinct from a genuine zero-result retrieval over content that *was* available. A partial case — some requested unstructured files return chunks, others do not — MUST proceed using only the files that returned chunks, and MUST NOT raise `FILE_CONTENT_UNAVAILABLE` in that case. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV10-022 | This spec's changes MUST NOT alter the classified behavior, agent selection, or final answer for a request whose `file_ids` are entirely structured (Spec FV10.5's pure-SQL path, unchanged) or whose `file_ids` are empty (the main orchestrator path, unchanged; see also Spec FV10.5 NFR-FV10-021 for the analogous guarantee on the no-`file_ids` question-routing path). |
| NFR-FV10-023 | Retrieval added by FR-FV10-065 MUST be bounded to the requested `file_ids`' own chunk count — it MUST NOT scan the org-wide knowledge base or any other user's files, regardless of question content. |

## 6. Data Contracts

### 6.1 File-Type Split

```python
def split_file_ids_by_type(
    file_ids: tuple[str, ...],
    files_by_id: Mapping[str, UserUploadedFile],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Returns (structured_file_ids, unstructured_file_ids), preserving
    each subset's relative order from the input. Every file_id in
    ``file_ids`` MUST already be a key in ``files_by_id`` — this function
    does not perform the ownership/readiness screening FR-FV10-069 requires
    that to have already happened."""
    structured = tuple(fid for fid in file_ids if files_by_id[fid].schema_json is not None)
    unstructured = tuple(fid for fid in file_ids if files_by_id[fid].schema_json is None)
    return structured, unstructured
```

### 6.2 `FileScopedRetriever`

```python
class FileScopedRetriever:
    """FR-FV10-065/069: RAG evidence scoped to exactly one request's
    file_ids, not the org-wide promoted knowledge base. No promotion step,
    no admin approval — file ownership was already checked by
    _validate_chat_query_file_ids before this is called."""

    def __init__(self, vector_source: FileVectorSource) -> None:
        self._vector_source = vector_source

    def retrieve(
        self, *, question: str, file_ids: tuple[str, ...], top_k: int = 5
    ) -> tuple[EvidenceItem, ...]:
        """Returns () if every file_id's chunks_with_vectors_for_file()
        call returns empty (FR-FV10-070 handles that case one level up,
        distinguishing "no content available" from "no relevant content")."""
```

Ranking reuses `chatbi.knowledge`'s existing keyword+vector scoring functions (`keyword_overlap_score`/`cosine_similarity`/`text_embedding` — un-privatized from `_keyword_score`/`_cosine_similarity` as part of this spec, since they now have a second legitimate caller outside that module) against a candidate set built from `chunks_with_vectors_for_file()` output instead of `InMemoryKnowledgeStore`'s document/chunk tables — no new ranking algorithm.

### 6.3 Evidence Provenance — an Existing Mechanism, Not a New Convention

Implementation finding: `ResultMerger.merge()` (`src/chatbi/orchestration/result_merger.py`) already accepts an `uploaded_file_evidence: tuple[EvidenceItem, ...] = ()` parameter, tags every item passed through it with `SourcedEvidenceItem(evidence=item, is_uploaded_file=True)`, and `_handle_file_data_chat_query`'s existing evidence-payload construction already renders `f"📎 {title}"` for any item with `is_uploaded_file=True` — none of this needed to be built; it was already wired for a `uploaded_file_evidence` input that no caller had ever populated. FR-FV10-065's retriever output is simply passed into this existing parameter:

```python
merged = file_result_merger.merge(
    file_output=file_output,  # or federated_output=...
    uploaded_file_evidence=uploaded_file_evidence,  # FileScopedRetriever's output
    knowledge_base_evidence=knowledge_base_evidence,  # unchanged, Spec FV10.1's org-wide store
)
```

`EvidenceItem.source_id` is still set to the originating file's own `file_id` (already `ufile_`-prefixed throughout this codebase — see `UserUploadedFile.file_id`), which is useful for traceability, but **the actual distinguishing mechanism the system uses is the `is_uploaded_file` boolean tag applied at `merge()`-time based on which parameter the evidence arrived through — not string-matching on `source_id`'s prefix.** This spec's original framing (FR-FV10-067/068 below) described a source_id-prefix-based frontend rendering scheme; that scheme was not needed, because a more direct mechanism already existed and only needed its input populated — no frontend code change was required at all.

### 6.4 New Error Reasons

```
NO_ANSWERABLE_FILE_SELECTED  — FR-FV10-066: neither table_result nor evidence_list
FILE_CONTENT_UNAVAILABLE     — FR-FV10-070: every unstructured file's chunk lookup was empty
```

Both map through the same `error_envelope(code=ApiErrorCode.REQ_INVALID_ARGUMENT, ...)` path Spec FV10.5 FR-FV10-061 established for `NO_STRUCTURED_FILE_SELECTED` — a 400, not a 500, per that spec's precedent. Per that same precedent, the top-level `error.code` in the response stays the shared `REQ_INVALID_ARGUMENT` for both — `ApiErrorCode` is a fixed enum shared across every endpoint, and `chat_query_v2`'s response builder (`_v2_answer_payload`) only passes through a fixed, known set of `data` fields, silently dropping anything else. The two conditions are distinguished by `error.message` text alone, exactly how Spec FV10.5 already distinguished `NO_STRUCTURED_FILE_SELECTED` from `INVALID_GENERATED_SQL`/`QUERY_RESOURCE_EXCEEDED` — not by a separate machine-readable field.

### 6.5 `_handle_file_data_chat_query` Control Flow (revised)

```python
structured_ids, unstructured_ids = split_file_ids_by_type(file_ids, files_by_id)

table_result = run_structured_query(structured_ids, question) if structured_ids else None

evidence_list: tuple[EvidenceItem, ...] = ()
file_content_unavailable = False
if unstructured_ids:
    evidence_list = file_scoped_retriever.retrieve(question=question, file_ids=unstructured_ids)
    if not evidence_list and _all_chunks_empty(unstructured_ids):
        file_content_unavailable = True

if table_result is None and not evidence_list:
    code = "FILE_CONTENT_UNAVAILABLE" if file_content_unavailable else "NO_ANSWERABLE_FILE_SELECTED"
    return error_envelope(code=ApiErrorCode.REQ_INVALID_ARGUMENT, message=..., trace_id=trace_id)

answer = answer_synthesizer.synthesize(
    question=question,
    safe_sql=sql_text or "",
    table_result=table_result or TableResult(columns=(), rows=()),
    evidence_list=evidence_list,
    ...
)
```

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-061 | A request with `file_ids` containing one structured and one unstructured file, where both have relevant content, returns an answer whose `table_result` is non-empty AND whose `evidence_list` is non-empty AND cites the unstructured file's `source_id`. |
| AC-FV10-062 | A request with `file_ids` containing only an unstructured file whose content answers the question succeeds (`200`), with an empty `table_result` and a non-empty `evidence_list` — this is the case that failed with `NO_STRUCTURED_FILE_SELECTED` before this spec. |
| AC-FV10-063 | Every item in a response's `evidence_list` sourced from a request-scoped file has `source_id` starting with `ufile_` and a `title` prefixed `📎 `; every item sourced from the knowledge base has `source_id` starting with `doc_` and an unprefixed `title`. |
| AC-FV10-064 | A request whose `file_ids` are all structured is answered identically (same agent calls, same `table_result`) to how Spec FV10.5 already answers it — no new code path is entered for this shape of request. |
| AC-FV10-065 | A request with `file_ids` containing only unstructured files, none of which has any relevant content, still succeeds with a low-relevance or empty `evidence_list` and a normal (not `FILE_CONTENT_UNAVAILABLE`) response, as long as `chunks_with_vectors_for_file()` returned a non-empty candidate set for at least one of them. |
| AC-FV10-066 | A request with `file_ids` containing only unstructured files where every one's `chunks_with_vectors_for_file()` call returns an empty tuple fails with an `error.message` distinguishable from the `NO_ANSWERABLE_FILE_SELECTED` case (§6.4) — both return `error.code == "REQ_INVALID_ARGUMENT"`, per Spec FV10.5's established precedent of message-only distinction. |
| AC-FV10-067 | A request with two unstructured `file_ids` where one returns chunks and the other returns none succeeds, using evidence from only the one that returned chunks — it does not fail with `FILE_CONTENT_UNAVAILABLE` merely because one of two files had no content available. |
| AC-FV10-068 | The retriever in FR-FV10-065 is never called with a `file_id` that `_validate_chat_query_file_ids` would reject — verified by construction (the retriever only receives the post-screening subset), not by a runtime check inside the retriever itself. |

## 8. Test Plan

### 8.1 Unit Tests — File-Type Split

| ID | Layer | Description |
|---|---|---|
| TC-FV10-163 | unit | `split_file_ids_by_type()` for a mix of two structured and one unstructured `file_id` returns the two structured ones in the first tuple and the one unstructured one in the second, both in original relative order. |
| TC-FV10-164 | unit | `split_file_ids_by_type()` for an all-unstructured input returns `((), (all file_ids))`. |

### 8.2 Unit Tests — `FileScopedRetriever`

| ID | Layer | Description |
|---|---|---|
| TC-FV10-165 | unit | `FileScopedRetriever.retrieve()` against one file's chunks returns an `EvidenceItem` whose `source_id` equals `f"ufile_{file_id}"` extracted correctly from a multi-chunk file (AC-FV10-063). |
| TC-FV10-166 | unit | `FileScopedRetriever.retrieve()` given two `file_ids` only returns chunks tagged with those two `file_id`s — never a chunk from a third file's vector-source entries, even if present in the same `FileVectorSource` instance (NFR-FV10-023). |
| TC-FV10-167 | unit | `FileScopedRetriever.retrieve()` ranks a chunk whose text closely matches the question above one that does not, for two chunks from the same file (reuses `knowledge.py`'s existing scoring — this test locks in that the reused function is actually being called, not re-implemented differently). |
| TC-FV10-168 | unit | `FileScopedRetriever.retrieve()` for `file_ids` whose `chunks_with_vectors_for_file()` all return `()` returns `()` — the empty-candidate-set case is handled by the caller (FR-FV10-070), not by raising here. |

### 8.3 Unit Tests — Answer Merging

| ID | Layer | Description |
|---|---|---|
| TC-FV10-169 | unit | Given a non-`None` `table_result` and a non-empty `evidence_list`, the merge logic calls `answer_synthesizer.synthesize()` with both populated, not just one (AC-FV10-061). |
| TC-FV10-170 | unit | Given `table_result=None` and a non-empty `evidence_list`, the merge logic calls `synthesize()` with `table_result=TableResult(columns=(), rows=())` and the evidence — no `NO_ANSWERABLE_FILE_SELECTED` (AC-FV10-062). |
| TC-FV10-171 | unit | Given `table_result=None` and `evidence_list=()` with `file_content_unavailable=False`, the merge logic returns `NO_ANSWERABLE_FILE_SELECTED`. |
| TC-FV10-172 | unit | Given `table_result=None`, `evidence_list=()`, and `file_content_unavailable=True`, the merge logic returns `FILE_CONTENT_UNAVAILABLE`, not `NO_ANSWERABLE_FILE_SELECTED` (AC-FV10-066). |

### 8.4 Integration Tests — HTTP

| ID | Layer | Description |
|---|---|---|
| TC-FV10-173 | integration | `POST /api/v2/chat/query` with `file_ids` = [one structured, one unstructured], both with matching content, returns `200` with non-empty `table_result` and `evidence_list` containing a `ufile_`-prefixed source (AC-FV10-061). |
| TC-FV10-174 | integration | `POST /api/v2/chat/query` with `file_ids` = [one unstructured file only] whose content answers the question returns `200` — regression-proves this no longer returns `400 NO_STRUCTURED_FILE_SELECTED` as it did under Spec FV10.5 alone (AC-FV10-062). |
| TC-FV10-175 | integration | `POST /api/v2/chat/query` with `file_ids` = [one unstructured file] whose vector source has no chunks for it returns `400` with an `error.message` distinguishable from the `NO_ANSWERABLE_FILE_SELECTED` case's message (AC-FV10-066). |
| TC-FV10-176 | integration | `POST /api/v2/chat/query` with `file_ids` = [all structured] produces byte-identical `table_result`/`sql_text` to the same request made against a build that only has Spec FV10.5's changes applied — a regression check for AC-FV10-064/NFR-FV10-022. |

### 8.5 Integration Test — Evidence Title Labeling

| ID | Layer | Description |
|---|---|---|
| TC-FV10-177 | integration (HTTP) | `POST /api/v2/chat/query` for a mixed structured+unstructured selection returns an `evidence_list` where the item sourced from the unstructured file has `title` prefixed `📎 ` and the items sourced from the knowledge base do not (AC-FV10-063, FR-FV10-068). No separate frontend test exists — this repository has no frontend test framework (no `*.test.*` files, no test runner in `frontend/package.json`), and the labeling itself is entirely server-side (§6.3), so an HTTP-level assertion on `evidence_list[].title` is a complete test of the actual behavior. |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-064 | AC-FV10-064 | TC-FV10-163, TC-FV10-164 |
| FR-FV10-065 | AC-FV10-061, AC-FV10-062 | TC-FV10-165, TC-FV10-166, TC-FV10-167, TC-FV10-173, TC-FV10-174 |
| FR-FV10-066 | AC-FV10-061, AC-FV10-062, AC-FV10-065 | TC-FV10-169, TC-FV10-170, TC-FV10-171 |
| FR-FV10-067 | AC-FV10-063 | TC-FV10-165 |
| FR-FV10-068 | AC-FV10-063 | TC-FV10-177 |
| FR-FV10-069 | AC-FV10-068 | — (verified by construction; see §10) |
| FR-FV10-070 | AC-FV10-066, AC-FV10-067 | TC-FV10-168, TC-FV10-172, TC-FV10-175 |
| NFR-FV10-022 | AC-FV10-064 | TC-FV10-176 |
| NFR-FV10-023 | — | TC-FV10-166 |

## 10. Implementation Notes

- FR-FV10-069 has no dedicated runtime test case because it is a structural guarantee, not a runtime branch: `FileScopedRetriever` never receives the full `file_ids` list, only the post-`split_file_ids_by_type()` subset, which itself only ever contains `file_id`s that `_validate_chat_query_file_ids` already screened before `_handle_file_data_chat_query` runs (Spec FV-10 FR-FV10-015). AC-FV10-068 records this as "verified by construction" for exactly this reason — the same reasoning Spec FV10.4's Implementation Notes used for FR-FV10-056 (an absence of a rewrite step has no direct positive test, only the call-count regression test that would fail if one were added).
- FR-FV10-070's "MUST NOT raise `FILE_CONTENT_UNAVAILABLE` in that case" clause (partial-availability case) exists because the natural-but-wrong implementation checks "is `evidence_list` empty?" instead of "did every file's lookup return zero chunks?" — those conditions coincide when there is one unstructured file, but diverge with two or more, where one file's zero-chunk lookup should not mask the other file's genuinely-available content. TC-FV10-168 and the partial case implied by AC-FV10-067 are the tests that would catch a regression to the simpler-but-wrong condition.
- This spec's `NO_ANSWERABLE_FILE_SELECTED` and `FILE_CONTENT_UNAVAILABLE` are deliberately two different codes, not one merged into the other, precisely because they call for different user-facing guidance: the first ("nothing here can answer your question") tells the user to pick a different file, the second ("this file's content isn't searchable right now") tells the user to re-upload — conflating them would mislead whichever half of the message is wrong for a given case, the same reasoning Spec FV10.5 §6 used to justify `FileNotPromotableError` over silently creating a document.
- No test case in this plan re-verifies Spec FV10.5's `FileDataAgent`/`FederatedQueryAgent`-internal structured/unstructured split (FR-FV10-057/058 of that spec) — this spec's `split_file_ids_by_type()` (§6.1) operates one layer higher, in `_handle_file_data_chat_query` itself, before either agent is called, and does not change what those agents do with the structured subset they are already only ever given.
- FR-FV10-067/068's source_id-prefix framing (as designed in the [source design doc](../../../../system_design/final-version/en/10-followups/06-hybrid-file-answering-for-mixed-selections.en.md)) turned out to be unnecessary once implementation started: `ResultMerger.merge()` already had an `uploaded_file_evidence` parameter and an `is_uploaded_file` tagging/title-prefixing mechanism, built for this exact purpose and simply never fed anything. §6.3 documents the correction. This is worth calling out explicitly because it changes what "done" means for FR-FV10-068 from "write new frontend rendering logic" to "populate an existing parameter correctly" — a smaller, lower-risk change than the spec originally implied, and the reason this spec's implementation required no `frontend/src/App.tsx` changes at all.
