# Spec FV10.9: A Data-Domain-Signal Safety Net for the File-Branch Relevance Gate

Source design:
- [10.9 A Data-Domain-Signal Safety Net for the File-Branch Relevance Gate design](../../../../system_design/final-version/en/10-followups/09-data-domain-signal-safety-net-for-the-relevance-gate.en.md)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (parent spec; this spec revises `QuestionClassifier` and `chat_query_v2()`'s file-branch routing decision)

This spec's parent routing gate — [10.8 A Question-Relevance Gate Before Routing to the File Branch](../../../../system_design/final-version/en/10-followups/08-question-relevance-gate-before-file-branch-routing.en.md) (`question_references_any_attached_file()` in `src/chatbi/agents/file_query_support.py`) — has no dedicated spec of its own; it was implemented directly from its design document, the same way Spec FV10.5's two fixes were. This spec treats 10.8's gate as an existing, already-tested dependency (see `tests/test_chat_query_with_files.py` and `tests/test_file_query_support.py`) and specifies only the safety net added on top of it.

---

## 1. Purpose

10.8's gate judges a question "not relevant" to an attached file whenever it shares no literal token with that file's column names or filename. That is a valid signal for "this vocabulary doesn't match the schema," but not proof that the main orchestrator has a real business table to send the question to instead — a question phrased with a business synonym the file's schema doesn't literally contain (e.g. "territory" for a column named `region`) would be misrouted away from a file it genuinely concerns, with nowhere else to actually answer it.

This spec adds a second, independent check: before acting on a "not relevant" verdict, confirm the question also reads as a real business-data question on its own terms — via `QuestionClassifier`'s existing `_DATA_DOMAIN_KEYWORDS` list, exposed as a new standalone method. Absent that corroborating signal, the request stays in the file branch instead of being routed to a destination equally unlikely to have an answer.

## 2. Scope

**In scope:**
- A new `QuestionClassifier.has_data_domain_signal(question)` method, reading only the existing `_DATA_DOMAIN_KEYWORDS` list, independent of `classify()`'s broader `TaskType.SQL_QUERY` computation.
- Wiring that method into `chat_query_v2()`'s file-branch routing decision as a corroborating check, evaluated only when 10.8's gate has already judged a request's attached files "not relevant" to the question.

**Out of scope:**
- Any change to 10.8's `question_references_any_attached_file()`/`question_references_attached_file()` predicates themselves — this spec only adds a second, independent check downstream of their verdict.
- Any change to `QuestionClassifier.classify()`'s own `TaskType.SQL_QUERY`/`needs_sql` computation — this spec reads `_DATA_DOMAIN_KEYWORDS` directly, not through that composite.
- Per-file relevance filtering inside a mixed structured/unstructured selection, and giving `FileDataAgent` visibility into a column's actual stored value format — both are separate, not-yet-implemented proposals (see [10.10](../../../../system_design/final-version/en/10-followups/10-per-file-relevance-filtering-in-mixed-selections.en.md) and [10.11](../../../../system_design/final-version/en/10-followups/11-value-sample-aware-schema-context.en.md)).

## 3. Actors

Reuses the actors defined in the parent FV-10 spec §3. No new actor.

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-077 | `QuestionClassifier` MUST expose a public `has_data_domain_signal(question: str) -> bool` method that returns `True` if and only if `question` (case-insensitively) contains at least one literal from `_DATA_DOMAIN_KEYWORDS`, independent of `classify()`'s `needs_sql`/`TaskType.SQL_QUERY` computation. |
| NFR-FV10-026 | When `chat_query_v2()`'s file-branch routing decision (10.8's `question_references_any_attached_file()`) judges a request's attached files "not relevant" to the question, the routing decision MUST be corroborated by calling `question_classifier.has_data_domain_signal(question)` before the request is routed away from the file branch. If that call also returns `False`, the request MUST route into the file branch instead of the main orchestrator. This corroboration MUST NOT run, and MUST have no effect, when 10.8's gate has already judged the request "relevant." |

## 5. Non-Functional Requirements

None beyond NFR-FV10-026 above, which is written as a non-functional constraint on *when* the corroboration check may run (this spec has no separate NFR section beyond that single cross-cutting guarantee).

## 6. Data Contracts

### 6.1 `QuestionClassifier.has_data_domain_signal()` — `src/chatbi/orchestration/routing.py`

```python
def has_data_domain_signal(self, question: str) -> bool:
    return self._contains_any(question.strip().lower(), self._DATA_DOMAIN_KEYWORDS)
```

Reuses the existing `_DATA_DOMAIN_KEYWORDS` tuple (`"revenue"`, `"order"`, `"orders"`, `"refund"`, `"active users"`, `"support"`, `"ticket"`, `"case volume"`, `"total"`, `"count"`, `"how many"`, `"average"`, `"sum"`, `"rate"`) and the existing `_contains_any()` helper, both already present in this class for `classify()`'s own use — no new keyword list, no new substring-matching logic.

### 6.2 `chat_query_v2()` Routing Gate — `src/chatbi/api/http.py`

```python
route_to_file_branch = bool(effective_file_ids) and question_references_any_attached_file(
    str(body["question"]), effective_files
)
if not route_to_file_branch and effective_files and not question_classifier.has_data_domain_signal(
    str(body["question"])
):
    route_to_file_branch = True
if route_to_file_branch:
    ...  # unchanged file branch
else:
    ...  # unchanged main-orchestrator branch
```

The corroboration `if` is gated on `not route_to_file_branch` — it is structurally unreachable when 10.8's gate already returned `True`, and `effective_files` — empty when `effective_file_ids` is empty (no files attached at all), which also makes the condition `False` by construction. Both are load-bearing for NFR-FV10-026's "MUST NOT run" clause; see §10.

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-069 | `QuestionClassifier().has_data_domain_signal(question)` returns `True` for a question containing a literal `_DATA_DOMAIN_KEYWORDS` match (e.g. `"Compare total ticket count by product in H1 2026."`, which contains `"ticket"`, `"total"`, and `"count"`). |
| AC-FV10-070 | `QuestionClassifier().has_data_domain_signal(question)` returns `False` for a question containing no `_DATA_DOMAIN_KEYWORDS` match (e.g. `"How's it looking overall?"`). |
| AC-FV10-071 | A chat request with one attached structured file, whose schema/filename share no token with the question (10.8's gate says "not relevant") and whose question contains a `_DATA_DOMAIN_KEYWORDS` match, is answered with `table_result_source` equal to `None` — the main orchestrator answered, not the file branch. |
| AC-FV10-072 | A chat request with one attached structured file, whose schema/filename share no token with the question (10.8's gate says "not relevant") and whose question contains no `_DATA_DOMAIN_KEYWORDS` match, is answered with `table_result_source` equal to `"file"` — the request stayed in the file branch. |
| AC-FV10-073 | A chat request whose attached file 10.8's gate already judges "relevant" (any literal token overlap, or any attached file being unstructured) is answered identically regardless of what `has_data_domain_signal()` would return for the same question — this spec's corroboration check has no observable effect on that request. |
| AC-FV10-074 | A chat request with no `file_ids` at all, and no session-inherited file selection, continues to route to the main orchestrator, unaffected by this spec. |

## 8. Test Plan

### 8.1 Unit Tests — `has_data_domain_signal()`

| ID | Layer | Description |
|---|---|---|
| TC-FV10-178 | unit | `QuestionClassifier().has_data_domain_signal("Compare total ticket count by product in H1 2026.")` returns `True` (AC-FV10-069). Implemented as `tests/test_agent_orchestration_routing.py::test_has_data_domain_signal_true_for_the_reported_bug_question`. |
| TC-FV10-179 | unit | `QuestionClassifier().has_data_domain_signal("How's it looking overall?")` returns `False` (AC-FV10-070). Implemented as `tests/test_agent_orchestration_routing.py::test_has_data_domain_signal_false_for_a_vague_question_with_no_business_vocabulary`. |

### 8.2 Integration Tests — HTTP Routing

| ID | Layer | Description |
|---|---|---|
| TC-FV10-180 | integration (HTTP) | `POST /api/v2/chat/query` with one attached structured file (`month`/`revenue` columns) and the question `"Compare total ticket count by product in H1 2026."` returns `200` with `data.table_result_source == None` (AC-FV10-071). Implemented as `tests/test_chat_query_with_files.py::test_chat_query_with_a_structured_file_irrelevant_to_the_question_routes_to_main_orchestrator`. |
| TC-FV10-181 | integration (HTTP) | `POST /api/v2/chat/query` with the same attached structured file and the question `"Please describe my numbers for this cycle."` (no schema/filename overlap, no `_DATA_DOMAIN_KEYWORDS` match) returns `200` with `data.table_result_source == "file"` (AC-FV10-072). Implemented as `tests/test_chat_query_with_files.py::test_chat_query_phrased_with_synonyms_the_schema_gate_misses_still_reaches_the_file_branch`. |

### 8.3 Regression Tests — Corroboration Does Not Alter Already-Relevant or File-less Requests

| ID | Layer | Description |
|---|---|---|
| TC-FV10-182 | regression | Every pre-existing test in `tests/test_chat_query_with_files.py`, `tests/test_chat_query_federated.py`, `tests/test_chat_query_file_rag_analytics.py`, and `tests/test_multi_turn_conversation.py` whose request is judged "relevant" by 10.8's gate (e.g. `test_chat_query_with_valid_file_ids_returns_file_sourced_table_result`, `test_chat_query_with_a_mixed_structured_and_unstructured_selection_answers_from_both`, `test_third_turn_inherits_the_second_turns_explicit_file_not_the_first`) continues to pass unchanged after this spec's changes (AC-FV10-073). No dedicated new test is added for this criterion beyond re-running the existing suite — see §10 for why this is a construction guarantee, not a runtime branch this spec's code newly exercises. |
| TC-FV10-183 | regression | `tests/test_chat_query_with_files.py::test_chat_query_without_file_ids_is_unaffected` and `tests/test_multi_turn_conversation.py::test_a_first_ever_question_with_empty_file_ids_uses_the_main_orchestrator` continue to pass unchanged (AC-FV10-074). |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-077 | AC-FV10-069, AC-FV10-070 | TC-FV10-178, TC-FV10-179 |
| NFR-FV10-026 | AC-FV10-071, AC-FV10-072, AC-FV10-073, AC-FV10-074 | TC-FV10-180, TC-FV10-181, TC-FV10-182, TC-FV10-183 |

## 10. Implementation Notes

- AC-FV10-073 has no dedicated new runtime test case, for the same reason Spec FV10.6's FR-FV10-069 did not (see that spec's own §10): it is a structural guarantee, not a runtime branch this spec's code newly exercises. `if not route_to_file_branch and effective_files and not question_classifier.has_data_domain_signal(...)` short-circuits on Python's `and` before `has_data_domain_signal()` is ever called when `route_to_file_branch` is already `True` — the corroboration check is unreachable in that case, not merely observed to have no effect. TC-FV10-182 re-runs the pre-existing suite as a regression check for exactly this reason, the same role Spec FV10.6's own "verified by construction" AC-FV10-068 played for `FileScopedRetriever`.
- This spec's own design process is itself worth recording precisely because it is a departure from how Spec FV10.5's and FV10.6's defects were found: the first design considered for NFR-FV10-026 — corroborating a "not relevant" verdict against `resolve_federated_pg_context()` (`business_table_catalog.py`) rather than `has_data_domain_signal()` — was checked against the exact acceptance scenario in AC-FV10-071 *before any code was written*, and found to return `None` for that question too (it only matches a question containing a business table's literal name, e.g. `"support_ticket_summary"`, which `"Compare total ticket count by product in H1 2026."` never does). Using it as the corroborating signal would have made AC-FV10-071 fail, not pass — the corroboration would have fired for the exact request this spec requires *not* to be re-routed into the file branch. §10.9 of the source design records this correction in full; this spec's FR-FV10-077/NFR-FV10-026 reflect the corrected design, not the first one considered.
- `_DATA_DOMAIN_KEYWORDS` is reused, not duplicated: `has_data_domain_signal()` reads the same private tuple `classify()` already reads for its own `has_data_signal` intermediate value (Spec FV10.5 §6.1). This spec does not add, remove, or retune any keyword in that list — a change to `_DATA_DOMAIN_KEYWORDS` made for Spec FV10.5's purposes automatically changes this spec's corroboration signal too, which is intentional: both uses share the same underlying question, "does this read like a real business-data question."
