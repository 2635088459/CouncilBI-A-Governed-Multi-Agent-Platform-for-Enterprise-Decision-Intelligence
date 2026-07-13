# Spec FV10.5: RAG-Only Routing and Knowledge Promotion Durability

Source design:
- [10.5 RAG-Only Routing and Knowledge Promotion Durability design](../../../system_design/final-version/en/10-followups/05-rag-only-routing-and-promotion-durability.en.md)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (parent spec; this spec revises `QuestionClassifier`, `ExecutionPlanBuilder`, `AnswerAssemblyVerifier`, `VerifierAgentRunner`, and `KnowledgePromotionService.promote_file()`)
- [Spec FV10.1: RAG Per-User Isolation](01-rag-per-user-isolation.spec.en.md) (this spec's §6.4 reuses `KnowledgePromotionService`'s ownership-stamping behavior unchanged)

---

## 1. Purpose

Two defects were found during Docker-based end-to-end verification of FV10.1–FV10.4, both between "a document is in the knowledge base" and "RAG actually answers from it":

1. A document-only question (e.g. "Explain what the onepager says about pricing") was routed through a mandatory SQL step it had no use for. The LLM produced invalid SQL, the guardrail denied it, and the request was rejected before RAG ever ran.
2. Promoting a file to the knowledge base could silently create a permanently-empty, unsearchable document with no error, if the file's chunked-and-embedded content was no longer available in the promoting process (e.g. after a restart).

This spec defines both fixes as testable requirements.

## 2. Scope

**In scope:**
- Question classification: deciding whether a question needs SQL at all, not assuming it always does.
- Execution planning: omitting the SQL step (and the SQL dependency on every fanout step) when SQL is not needed.
- Orchestrator control flow: skipping the SQL-generation LLM call when SQL is not needed.
- Final answer verification: accepting an answer grounded in `evidence_list` alone, with no SQL output.
- Agent-level verification: not flagging an absent SQL text as a finding when no SQL step was planned.
- Knowledge promotion: failing with a clear error, and creating no partial state, when a file has no chunks available to promote.

**Out of scope:**
- Making `FileVectorSource` durable across process restarts (see the design doc §7 "Known Limitation"). This spec only requires the failure to be loud and side-effect-free, not the underlying constraint to be removed.
- Any change to the keyword lists themselves beyond what is needed to add the SQL-necessity signal (§6.1) — tuning individual keywords for retrieval quality is not part of this spec.
- Retrieval relevance ranking (`InMemoryKnowledgeStore._rank_records`) — unchanged by this spec.

## 3. Actors

Reuses the actors defined in the parent FV-10 spec §3. No new actor.

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-057 | `QuestionClassifier.classify()` MUST include `TaskType.SQL_QUERY` in its result only when the question matches a data-domain keyword, a chart keyword, or an analytics keyword, or matches no RAG keyword at all. A question that matches a RAG keyword and none of the other three signal sets MUST NOT include `TaskType.SQL_QUERY`. |
| FR-FV10-058 | `ExecutionPlanBuilder.build()` MUST NOT include a SQL step in the returned plan, and MUST NOT set any fanout step's `depends_on` to `(AgentName.SQL,)`, when `TaskType.SQL_QUERY` is absent from the input task-type set. When present, behavior is unchanged from the pre-existing plan shape. |
| FR-FV10-059 | The orchestrator MUST NOT issue a SQL-generation LLM request for a question whose classified task types do not include `TaskType.SQL_QUERY`; `sql_candidate` MUST be the empty string in that case, with no `WarningMessage` produced by skipping it. |
| FR-FV10-060 | `AnswerAssemblyVerifier` MUST accept an answer with empty `sql_text` and empty `table_result.columns` as satisfying its assembly checks when `evidence_list` is non-empty. It MUST still reject an answer whose `evidence_list` is empty AND whose `sql_text`/`table_result.columns` are empty, exactly as before this spec. |
| FR-FV10-061 | `KnowledgePromotionService.promote_file()` MUST raise `FileNotPromotableError` and MUST NOT create, update, or write to `VectorStore`, the live `InMemoryKnowledgeStore`, the Postgres `knowledge.*` tables, or the source file's `promoted_to_doc_id`, when `FileVectorSource.chunks_with_vectors_for_file(file_id)` returns an empty tuple for an otherwise-promotable file. |
| FR-FV10-062 | When the orchestrator constructs `VerifierAgentRunner` for a question with no SQL step planned, it MUST pass `sql_text=None`, not an empty string. `VerifierAgentRunner` MUST NOT include a missing-SQL finding for a `None` `sql_text` (pre-existing behavior — the empty-string case is what this spec's call site avoids producing). |
| FR-FV10-063 | `runtime_query_result_record_from_response()` MUST return `None`, and MUST NOT construct a `RuntimeQueryResultRecord`, when the response's `sql_text` field is missing, not a string, or an empty/whitespace-only string. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV10-021 | This spec's routing changes MUST NOT alter the classified task types, plan shape, or final answer for any question that requires both SQL and RAG together (e.g. "Why did revenue drop?"), or for any SQL-only, chart, or analytics question. Verified by regression test cases that exercise the pre-existing combined and SQL-only paths after this spec's changes are applied. |

## 6. Data Contracts

### 6.1 `QuestionClassifier` — SQL-Necessity Signal

```python
_DATA_DOMAIN_KEYWORDS = (
    "revenue", "order", "orders", "refund", "active users",
    "support", "ticket", "case volume", "total", "count",
    "how many", "average", "sum", "rate",
)

def classify(self, question: str, *, file_ids: tuple[str, ...] = ()) -> frozenset[TaskType]:
    is_rag = self._contains_any(normalized, self._RAG_KEYWORDS)
    is_analytics = self._contains_any(normalized, self._ANALYTICS_KEYWORDS)
    is_chart = self._contains_any(normalized, self._CHART_KEYWORDS)
    has_data_signal = self._contains_any(normalized, self._DATA_DOMAIN_KEYWORDS)

    needs_sql = has_data_signal or is_chart or is_analytics or not is_rag
    # TaskType.SQL_QUERY is added to the result set iff needs_sql is True.
```

`not is_rag` is the default-preserving clause: any question that does not match a RAG keyword still needs SQL exactly as before this spec.

### 6.2 `ExecutionPlanBuilder` — Conditional SQL Step

```python
def build(self, task_types: frozenset[TaskType] | TaskType) -> ExecutionPlan:
    needs_sql = TaskType.SQL_QUERY in task_types
    sql_steps = (AgentPlanStep(AgentName.SQL, ExecutionStage.SQL),) if needs_sql else ()
    sql_dependency: tuple[AgentName, ...] = (AgentName.SQL,) if needs_sql else ()
    # every fanout step (RAG, VISUALIZATION, ANALYTICS, FILE_DATA) now takes
    # depends_on=sql_dependency instead of a hardcoded (AgentName.SQL,)
```

### 6.3 Orchestrator — Conditional SQL Generation

```python
task_types = self._classifier.classify(request.question)
needs_sql = TaskType.SQL_QUERY in task_types
if needs_sql:
    sql_candidate, llm_warning = self._build_sql_candidate(request, active_trace_id, conversation_messages_tuple)
else:
    sql_candidate, llm_warning = "", None
```

Table result assembly mirrors this: when `not needs_sql`, `table_result` is `TableResult(columns=(), rows=())` and no readonly-query execution is attempted (no spurious `INTERNAL_ERROR` warning from running an empty SQL string).

### 6.4 `AnswerAssemblyVerifier` — Evidence-Only Grounding

```python
def _findings(self, answer: QueryAnswer) -> tuple[str, ...]:
    findings: list[str] = []
    if not answer.answer_text.strip():
        findings.append("answer_text is required.")
    if not answer.evidence_list:
        if not answer.sql_text.strip():
            findings.append("sql_text is required.")
        if not answer.table_result.columns:
            findings.append("table_result.columns is required.")
    if not answer.trace_id.strip():
        findings.append("trace_id is required.")
    return tuple(findings)
```

### 6.5 `VerifierAgentRunner` — `sql_text=None` for "Not Applicable"

`VerifierAgentRunner._findings()` (pre-existing, unchanged): `if self.sql_text is not None and not self.sql_text.strip(): findings.append("SQL text is missing.")`. The orchestrator's call site changes:

```python
AgentName.VERIFIER: VerifierAgentRunner(
    verified=True,
    confidence=0.9,
    reason="Mock answer passes baseline verification.",
    sql_text=sql_candidate or None,  # "" -> None when no SQL was planned
),
```

### 6.6 `KnowledgePromotionService.promote_file()` — Fail Before Any Write

```python
def promote_file(self, file_id: str, *, role: UserRoleV2, org_id: str) -> UserUploadedFile:
    _require_admin(role)
    file = self._repository.get(file_id)
    if file is None or file.org_id != org_id or file.file_type != "unstructured" or file.status != "ready":
        raise FileNotPromotableError(file_id)

    chunks_with_vectors = self._vector_source.chunks_with_vectors_for_file(file_id)
    if not chunks_with_vectors:
        raise FileNotPromotableError(file_id)

    # document_id is generated, and every write (VectorStore, live
    # InMemoryKnowledgeStore, Postgres knowledge.* tables, repository.save)
    # happens only after this point.
```

### 6.7 `runtime_query_result_record_from_response()` — Skip, Don't Crash

```python
def runtime_query_result_record_from_response(*, trace_id, session_id, user_id, org_id=None, question, data):
    ...
    sql_text = data_mapping.get("sql_text")
    if not isinstance(sql_text, str) or not sql_text.strip():
        return None
    ...
    return RuntimeQueryResultRecord(..., sql_text=sql_text, ...)
```

Both call sites (`chat_query_v2` in `http.py`, and the `/api/v1/chat/query`-adjacent handler) already treat a `None` return as "nothing to save" — this section only changes what counts as "nothing to save."

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-052 | A question that matches a RAG keyword and no data-domain, chart, or analytics keyword classifies to exactly `{TaskType.RAG_EXPLANATION}` — `TaskType.SQL_QUERY` is absent. |
| AC-FV10-053 | A question that matches both a RAG keyword and a data-domain keyword (e.g. "Why did revenue drop?") classifies to `{TaskType.SQL_QUERY, TaskType.RAG_EXPLANATION}`, unchanged from pre-spec behavior. |
| AC-FV10-054 | A plan built from `{TaskType.RAG_EXPLANATION}` alone has exactly two steps — `(RAG, VERIFIER)` — with the RAG step's `depends_on` equal to `()` and the verifier's `depends_on` equal to `(AgentName.RAG,)`. |
| AC-FV10-055 | Given a knowledge store containing a document whose content answers a document-only question, `SimpleOrchestrator.answer()` for that question returns a `QueryAnswer` with `sql_text == ""`, `table_result == TableResult(columns=(), rows=())`, non-empty `evidence_list` citing that document, and `warnings == ()` (no `VERIFICATION_FAILED` from either verifier). |
| AC-FV10-056 | An answer with empty `sql_text`/`table_result.columns` and non-empty `evidence_list` passes `AnswerAssemblyVerifier.verify()` unchanged (no warning appended, confidence unchanged). |
| AC-FV10-057 | An answer with empty `sql_text`/`table_result.columns` and empty `evidence_list` still fails `AnswerAssemblyVerifier.verify()` with a `VERIFICATION_FAILED` warning listing both missing fields, and confidence capped at 0.5. |
| AC-FV10-058 | Calling `promote_file()` for a `ready`, `unstructured`, org-matching file whose vector source has no chunks for it raises `FileNotPromotableError`, and afterward: the `VectorStore` has no new document, the live `InMemoryKnowledgeStore` has no new document, and the file's `promoted_to_doc_id` in the repository remains `None`. |
| AC-FV10-059 | Calling `promote_file()` for the same kind of file when its vector source does have chunks (the pre-existing success path) is unaffected: the file is promoted, `promoted_to_doc_id` is set, and the document is immediately retrievable via `InMemoryKnowledgeStore.retrieve()` in the same process. |
| AC-FV10-060 | A `POST /api/v2/chat/query` request for a document-only question returns HTTP 200 (not 500), and, when a `RuntimeQueryResultStore` is configured, no record is saved for that request's `trace_id`. |

## 8. Test Plan

### 8.1 Unit Tests — Question Classification

| ID | Layer | Description |
|---|---|---|
| TC-FV10-153 | unit | `QuestionClassifier().classify("Explain what the onepager says about pricing.")` returns `frozenset({TaskType.RAG_EXPLANATION})` — no `TaskType.SQL_QUERY` (AC-FV10-052). |
| TC-FV10-154 | unit | `QuestionClassifier().classify("Why did revenue drop?")` returns `frozenset({TaskType.SQL_QUERY, TaskType.RAG_EXPLANATION})` (AC-FV10-053, regression). |

### 8.2 Unit Tests — Execution Planning

| ID | Layer | Description |
|---|---|---|
| TC-FV10-155 | unit | `ExecutionPlanBuilder().build(frozenset({TaskType.RAG_EXPLANATION}))` produces `plan.agents() == (AgentName.RAG, AgentName.VERIFIER)`, with `plan.steps[0].depends_on == ()` and `plan.steps[1].depends_on == (AgentName.RAG,)` (AC-FV10-054). |

### 8.3 Unit Tests — Answer Verification

| ID | Layer | Description |
|---|---|---|
| TC-FV10-156 | unit | An answer with empty `sql_text`/`table_result` and one `EvidenceItem` in `evidence_list` passes `AnswerAssemblyVerifier.verify()` unchanged: no warning, same confidence (AC-FV10-056). |
| TC-FV10-157 | unit | An answer with empty `sql_text`/`table_result` and empty `evidence_list` still fails verification with both `"sql_text is required."` and `"table_result.columns is required."` in the warning message, confidence `0.5` (AC-FV10-057). |

### 8.4 Unit Tests — Knowledge Promotion

| ID | Layer | Description |
|---|---|---|
| TC-FV10-158 | unit | `promote_file()` for a ready, unstructured file with an empty vector source raises `FileNotPromotableError`; afterward the `VectorStore`, the live `InMemoryKnowledgeStore`, and the file's `promoted_to_doc_id` are all unchanged (AC-FV10-058). |
| TC-FV10-159 | unit (regression) | `promote_file()` for the same kind of file with one seeded chunk succeeds and the promoted document is immediately retrievable via `InMemoryKnowledgeStore.retrieve()` (AC-FV10-059) — pre-existing test, re-verified unaffected by this spec's changes. |

### 8.5 Orchestrator-Level Test — End-to-End Document-Only Answer

| ID | Layer | Description |
|---|---|---|
| TC-FV10-160 | orchestrator (integration) | `SimpleOrchestrator.answer()` for a document-only question, against a knowledge store containing the answering document, returns `sql_text == ""`, `table_result == TableResult(columns=(), rows=())`, one matching evidence item, `warnings == ()`, and `confidence > 0.5` — this is the test that caught FR-FV10-062 (§6.5): it fails if `VerifierAgentRunner` receives `sql_text=""` instead of `None` (AC-FV10-055). |

### 8.6 Regression Tests — Existing SQL/RAG Paths Unaffected

| ID | Layer | Description |
|---|---|---|
| TC-FV10-161 | regression | Pre-existing orchestrator tests exercising SQL-only, chart, analytics, and combined SQL+RAG questions (e.g. `test_orchestrator_uses_knowledge_store_for_rag_evidence`, `test_orchestrator_attaches_chart_spec_for_kpi_query`) pass unchanged after this spec's classifier/plan-builder/verifier changes (NFR-FV10-021). |

### 8.7 HTTP-Level Test — Document-Only Question Does Not Crash the Endpoint

| ID | Layer | Description |
|---|---|---|
| TC-FV10-162 | integration (HTTP) | `POST /api/v2/chat/query` with a document-only question, against an app configured with a `RuntimeQueryResultStore`, returns HTTP 200, and the store has no record for the response's `trace_id` — this is the test that caught FR-FV10-063: it fails with an unhandled 500 if `runtime_query_result_record_from_response()` still constructs `RuntimeQueryResultRecord(sql_text="")` (AC-FV10-060). |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-057 | AC-FV10-052, AC-FV10-053 | TC-FV10-153, TC-FV10-154 |
| FR-FV10-058 | AC-FV10-054 | TC-FV10-155 |
| FR-FV10-059 | AC-FV10-055 | TC-FV10-160 |
| FR-FV10-060 | AC-FV10-056, AC-FV10-057 | TC-FV10-156, TC-FV10-157 |
| FR-FV10-061 | AC-FV10-058, AC-FV10-059 | TC-FV10-158, TC-FV10-159 |
| FR-FV10-062 | AC-FV10-055 | TC-FV10-160 |
| FR-FV10-063 | AC-FV10-060 | TC-FV10-162 |
| NFR-FV10-021 | AC-FV10-053 | TC-FV10-154, TC-FV10-161 |

## 10. Implementation Notes

- FR-FV10-057's `not is_rag` clause is what keeps this spec's blast radius narrow: SQL stays the default for every question except one that matches a RAG keyword and nothing else. A question with an unrecognized RAG-adjacent phrasing but no data-domain keyword and no other signal will still fall through to SQL exactly as before this spec — this spec makes RAG-only routing possible, it does not attempt to make the classifier's keyword coverage exhaustive.
- FR-FV10-062 was not part of the original design review — it was found by writing TC-FV10-160 (an orchestrator-level, not unit-level, test) before confirming the fix was complete. `AnswerAssemblyVerifier` (FR-FV10-060) and `VerifierAgentRunner` (FR-FV10-062) are two independent verifiers checking a similar-looking but distinct invariant; fixing one does not fix the other, and unit tests scoped to just one of them would not have caught this. This is the concrete argument for keeping TC-FV10-160 in the test plan even though its constituent behaviors are each covered by a narrower unit test elsewhere.
- FR-FV10-063 was found the same way one layer further out: after FR-FV10-060 and FR-FV10-062 were both fixed and TC-FV10-156/157/160 all passed, a live HTTP request against the running application still returned 500. `RuntimeQueryResultRecord` is a third, independent place enforcing "SQL text is required," reached only through response serialization in `http.py`, not through `QueryAnswer` construction — no unit or orchestrator-level test in this spec's suite exercises that code path. TC-FV10-162 is deliberately an HTTP-level test (`TestClient` against `create_app()`) rather than a narrower unit test on `runtime_query_result_record_from_response()` alone, specifically because the bug it catches is in how a *response envelope* gets turned into a persistence record, not in a function signature that a unit test's caller could get right by construction.
- FR-FV10-061's "MUST NOT create, update, or write to" clause is deliberately specific about *where* nothing must be written (`VectorStore`, live `InMemoryKnowledgeStore`, Postgres, `promoted_to_doc_id`) rather than just "must fail" — the original bug was not that promotion failed to report success, it was that it reported success while writing an unsearchable half-result. A test that only checks for the exception, without checking for absence of partial writes, would not catch a regression back to that shape of bug.
- This spec does not introduce a test case for the Postgres-backed `knowledge_connection` branch of `_index_into_live_rag()` (§6.6 of the design doc) beyond what FV10.1's existing test suite already covers (`test_http_promoted_document_surfaces_in_evidence_for_the_promoting_user` and neighboring tests) — FR-FV10-061's guard runs before that branch is ever reached, so no new Postgres-path test is needed for this spec specifically.
