# Spec FV10.13: Guardrail Deny-Reason Preservation for Non-SELECT LLM Output

中文版：[../../zh-CN/10-followups/13-guardrail-deny-reason-preservation.spec.zh-CN.md](../../zh-CN/10-followups/13-guardrail-deny-reason-preservation.spec.zh-CN.md)

Source design:
- [10.13 Guardrail Deny-Reason Preservation for Non-SELECT LLM Output](../../../../system_design/final-version/en/10-followups/13-guardrail-deny-reason-preservation.en.md)
- [Spec FV-10: User File Upload and Hybrid Data Analysis](../10-user-file-upload-and-hybrid-analysis.spec.en.md) (sibling spec; this spec's requirements are independent of the file-upload feature — the guardrail chain it revises is shared infrastructure exercised by both file and non-file questions)

This spec was written **spec-first**, before any of §3/§4's design was implemented, per this project's usual SDD+TDD order. Every functional requirement below has at least one acceptance criterion and at least one test case; every test case traces back to a requirement. Test cases were written to run **red** against the pre-implementation code, then confirmed **green** afterward — see §10 for one requirement (AC-FV10-103/TC-FV10-215) this project's test suite has no existing harness to verify automatically, and how it was verified instead.

---

## 1. Purpose

A read-only, explanatory question ("explain, step by step, how you calculated the churn rate...") was blocked with a message claiming the request attempted to modify data. Reading the full chain the request traversed — `SqlStatementValidator.validate()` → `SimpleSqlGuardrail._deny()` → `api_error_for_warning()` → the frontend's `SQL_GUARDRAIL_BLOCKED` branch — shows the distinction between "the model's output contained a real DML/DDL keyword" and "the model's output simply wasn't a SELECT statement for an unrelated reason" is computed once, correctly, inside `validate()`'s two branches, and then discarded three times in a row: both branches return the same `SqlValidationViolationCode.NON_SELECT_STATEMENT`; `SimpleSqlGuardrail._deny()` maps every violation code to the same `ErrorCode.SQL_DENY_STATEMENT`; and `api_error_for_warning()` maps `SQL_DENY_STATEMENT` together with two unrelated denial reasons (`SQL_DENY_OBJECT`, `SQL_DENY_FUNCTION`) to one `ApiErrorCode.SQL_GUARDRAIL_BLOCKED`.

This spec introduces one new violation code, one new `ErrorCode`, and one new `ApiErrorCode` — threading a single distinction (dangerous-keyword match vs. non-SQL model output) through all four layers so the frontend can show an accurate message for the case that was reported.

## 2. Scope

**In scope:**
- A new `SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT` value, returned by `SqlStatementValidator.validate()`'s final prefix check when no dangerous-statement keyword was found.
- A new `ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT` value, and `SimpleSqlGuardrail`'s denial-construction logic choosing between it and the existing `ErrorCode.SQL_DENY_STATEMENT` based on the validator's violation code.
- A new `ApiErrorCode.SQL_NOT_QUERYABLE` value, and a corresponding branch in `api_error_for_warning()`.
- A new frontend message branch for `SQL_NOT_QUERYABLE` in `frontend/src/App.tsx`.

**Out of scope:**
- `SqlValidationViolationCode.EMPTY_SQL`, `MULTIPLE_STATEMENTS`, and `STRUCTURAL_RISK` — all three continue mapping to `ErrorCode.SQL_DENY_STATEMENT`/`ApiErrorCode.SQL_GUARDRAIL_BLOCKED` unchanged; see the source design's §6 for why these are not part of this fix.
- Making SQL generation succeed for questions with no matching table or metric — this spec only makes the reported failure's *displayed reason* accurate, not the underlying question answerable.
- Any schema-specific detail in the new frontend message (e.g. naming the missing table) — `SqlValidationResult` carries no schema-awareness at this layer.
- Any change to `FederatedQueryAgent`'s own, separate guardrail path (`_guardrail_check()` in `src/chatbi/agents/federated_query_agent.py`, backed by `find_blocked_statement()`) — that is a distinct guardrail implementation from `SimpleSqlGuardrail`/`SqlStatementValidator`, not touched here.

## 3. Actors

Reuses the actors defined in the parent FV-10 spec §3. No new actor.

## 4. Functional Requirements

| ID | Requirement |
|---|---|
| FR-FV10-087 | `SqlStatementValidator.validate()` MUST return `SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT` when the normalized SQL text does not start with an allowed statement prefix (`select `/`with `) AND does not match `_DANGEROUS_STATEMENT_PATTERN`. It MUST continue returning `SqlValidationViolationCode.NON_SELECT_STATEMENT` when `_DANGEROUS_STATEMENT_PATTERN` matches, regardless of prefix. |
| FR-FV10-088 | `SimpleSqlGuardrail.check()` MUST construct its denial `GuardrailResult` with `ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT` when `SqlStatementValidator.validate()`'s result has `violation_code == SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT`, and with `ErrorCode.SQL_DENY_STATEMENT` for every other violation code (`EMPTY_SQL`, `MULTIPLE_STATEMENTS`, `STRUCTURAL_RISK`, `NON_SELECT_STATEMENT`), unchanged. |
| FR-FV10-089 | `api_error_for_warning()` MUST map `ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT` to a new `ApiErrorCode.SQL_NOT_QUERYABLE`. It MUST continue mapping `ErrorCode.SQL_DENY_STATEMENT`, `ErrorCode.SQL_DENY_OBJECT`, and `ErrorCode.SQL_DENY_FUNCTION` to `ApiErrorCode.SQL_GUARDRAIL_BLOCKED`, unchanged. |
| FR-FV10-090 | The frontend (`frontend/src/App.tsx`) MUST render a distinct error message for `errorCode === "SQL_NOT_QUERYABLE"` whose title and body do not state or imply that the request attempted to insert, update, or delete data. |

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-FV10-030 | This spec's changes MUST NOT alter the `ErrorCode`, `ApiErrorCode`, or frontend message produced for: (a) SQL text matching `_DANGEROUS_STATEMENT_PATTERN` while also starting with an allowed prefix (an edge case `_DANGEROUS_STATEMENT_PATTERN` is checked first regardless of prefix, per FR-FV10-087); (b) an `ErrorCode.SQL_DENY_OBJECT` denial (disallowed table); (c) an `ErrorCode.SQL_DENY_FUNCTION` denial (disallowed SQL function). |

## 6. Data Contracts

### 6.1 `SqlValidationViolationCode` — `src/chatbi/governance/sql_validator.py`

```python
class SqlValidationViolationCode(StrEnum):
    EMPTY_SQL = "empty_sql"
    MULTIPLE_STATEMENTS = "multiple_statements"
    STRUCTURAL_RISK = "structural_risk"
    NON_SELECT_STATEMENT = "non_select_statement"
    UNRECOGNIZED_QUERY_OUTPUT = "unrecognized_query_output"
```

`SqlStatementValidator.validate()`'s final two checks become:

```python
if _DANGEROUS_STATEMENT_PATTERN.search(normalized_sql):
    return self._deny(
        normalized_sql,
        SqlValidationViolationCode.NON_SELECT_STATEMENT,
        "Only SELECT statements are allowed.",
    )

if not normalized_sql.lower().startswith(_ALLOWED_STATEMENT_PREFIXES):
    return self._deny(
        normalized_sql,
        SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT,
        "The model's output was not a single read-only query.",
    )
```

### 6.2 `ErrorCode` — `src/chatbi/core/contracts.py`

```python
class ErrorCode(StrEnum):
    ...
    SQL_DENY_STATEMENT = "SQL_DENY_STATEMENT"
    SQL_DENY_UNRECOGNIZED_OUTPUT = "SQL_DENY_UNRECOGNIZED_OUTPUT"
    ...
```

### 6.3 `SimpleSqlGuardrail` — `src/chatbi/governance/simple_guardrail.py`

```python
def check(self, sql_text: str, request: QueryRequest, trace_id: str) -> GuardrailResult:
    validation = self._statement_validator.validate(sql_text)
    if not validation.passed:
        result = self._deny_for_violation(trace_id, validation)
        return self._record_decision(sql_text, request, result)
    ...

def _deny_for_violation(
    self, trace_id: str, validation: SqlValidationResult
) -> GuardrailResult:
    error_code = (
        ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT
        if validation.violation_code is SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT
        else ErrorCode.SQL_DENY_STATEMENT
    )
    return GuardrailResult(
        decision=GuardrailDecision.DENY,
        trace_id=trace_id,
        error_code=error_code,
        message=validation.message or "SQL was denied.",
    )
```

The pre-existing `_deny(self, trace_id, message)` helper is removed in favor of `_deny_for_violation`, which takes the full `SqlValidationResult` instead of a bare message string — every call site inside `check()` that previously called `_deny()` is updated to call `_deny_for_violation()`.

### 6.4 `ApiErrorCode` and `api_error_for_warning()` — `src/chatbi/api/models.py`

```python
class ApiErrorCode(StrEnum):
    ...
    SQL_GUARDRAIL_BLOCKED = "SQL_GUARDRAIL_BLOCKED"
    SQL_NOT_QUERYABLE = "SQL_NOT_QUERYABLE"
    ...

def api_error_for_warning(warning: WarningMessage) -> ApiErrorCode:
    if warning.code is ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT:
        return ApiErrorCode.SQL_NOT_QUERYABLE
    if warning.code in {
        ErrorCode.SQL_DENY_STATEMENT,
        ErrorCode.SQL_DENY_OBJECT,
        ErrorCode.SQL_DENY_FUNCTION,
    }:
        return ApiErrorCode.SQL_GUARDRAIL_BLOCKED
    if warning.code is ErrorCode.QUERY_TIMEOUT:
        return ApiErrorCode.QUERY_TIMEOUT
    if warning.code is ErrorCode.AGENT_PARTIAL_FAILURE:
        return ApiErrorCode.AGENT_PARTIAL_FAILURE
    if warning.code is ErrorCode.UNSUPPORTED_QUESTION:
        return ApiErrorCode.REQ_INVALID_ARGUMENT
    return ApiErrorCode.INTERNAL_ERROR
```

### 6.5 Frontend Message Branch — `frontend/src/App.tsx`

```tsx
errorCode === "SQL_NOT_QUERYABLE" ? (
  <div className="answer-blocked answer-blocked--warn">
    <div className="blocked-icon">⚠</div>
    <div className="blocked-body">
      <p className="blocked-title">Can't generate a query for this question</p>
      <p className="blocked-desc">
        This question doesn't match a read-only query we can run against the
        available data. Try rephrasing it as a specific data question, or
        check that the data you're asking about exists in a connected table.
      </p>
    </div>
  </div>
) : errorCode === "SQL_GUARDRAIL_BLOCKED" ? (
  /* unchanged */
  ...
```

Placed as a sibling branch before the existing `SQL_GUARDRAIL_BLOCKED` check in the same conditional chain (`App.tsx:1143` onward), reusing the existing `answer-blocked--warn` styling already used by the `VALIDATION_ERROR` and `REQ_INVALID_ARGUMENT` branches immediately below it, rather than the `⊘`/blocking-red styling reserved for a genuine guardrail denial.

### 6.6 HTTP Status Code — `src/chatbi/api/http.py` (found during implementation — see §10)

```python
def status_code_for_envelope(envelope: ApiEnvelope) -> int:
    ...
    if envelope.code is ApiErrorCode.SQL_GUARDRAIL_BLOCKED:
        return 403
    if envelope.code is ApiErrorCode.SQL_NOT_QUERYABLE:
        return 400
    return 200
```

Not part of §6's original data contracts — `status_code_for_envelope()` has no branch for any code it doesn't recognize, so without this addition a `SQL_NOT_QUERYABLE` response would have returned HTTP `200` with a non-null `error` field, an internally inconsistent envelope. `400` matches this function's existing `REQ_INVALID_ARGUMENT` mapping, the closest existing precedent for "the request as phrased cannot be fulfilled" rather than a security denial.

## 7. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-FV10-096 | `SqlStatementValidator().validate("UPDATE revenue_by_month SET revenue = 0")` returns `violation_code == SqlValidationViolationCode.NON_SELECT_STATEMENT` (unchanged from current behavior). |
| AC-FV10-097 | `SqlStatementValidator().validate("I don't have a churn table to query against.")` returns `violation_code == SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT`. |
| AC-FV10-098 | `SimpleSqlGuardrail().check(sql_text="UPDATE revenue_by_month SET revenue = 0", ...)` returns a `GuardrailResult` with `error_code == ErrorCode.SQL_DENY_STATEMENT` (unchanged). |
| AC-FV10-099 | `SimpleSqlGuardrail().check(sql_text="I don't have a churn table to query against.", ...)` returns a `GuardrailResult` with `error_code == ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT`. |
| AC-FV10-100 | `api_error_for_warning(WarningMessage(code=ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT, ...))` returns `ApiErrorCode.SQL_NOT_QUERYABLE`. |
| AC-FV10-101 | `api_error_for_warning()` called with each of `ErrorCode.SQL_DENY_STATEMENT`, `ErrorCode.SQL_DENY_OBJECT`, and `ErrorCode.SQL_DENY_FUNCTION` still returns `ApiErrorCode.SQL_GUARDRAIL_BLOCKED` for all three (unchanged). |
| AC-FV10-102 | `POST /api/v2/chat/query` with a question and an LLM stub configured to return prose (no SELECT/WITH prefix, no dangerous keyword) — reproducing the reported churn-rate audit-trail question's likely model output — returns a response whose `code` is `"SQL_NOT_QUERYABLE"` (not `"SQL_GUARDRAIL_BLOCKED"`) with HTTP status `400` (§6.6). |
| AC-FV10-103 | The frontend renders the §6.5 message (title: "Can't generate a query for this question") for `errorCode === "SQL_NOT_QUERYABLE"`, and continues rendering the existing §2.3 message (title: "Query blocked — data modifications are not permitted") unchanged for `errorCode === "SQL_GUARDRAIL_BLOCKED"`. |

## 8. Test Plan

### 8.1 Unit Tests — `SqlStatementValidator`

| ID | Layer | Description |
|---|---|---|
| TC-FV10-208 | unit | `validate("UPDATE revenue_by_month SET revenue = 0")` → `NON_SELECT_STATEMENT` (AC-FV10-096). Implemented as `tests/test_sql_validator.py::test_sql_statement_validator_denies_dangerous_statement_as_non_select_statement`. |
| TC-FV10-209 | unit | `validate("I don't have a churn table to query against.")` → `UNRECOGNIZED_QUERY_OUTPUT` (AC-FV10-097). Implemented as `test_sql_statement_validator_denies_prose_output_as_unrecognized_query_output`. |

### 8.2 Unit Tests — `SimpleSqlGuardrail`

| ID | Layer | Description |
|---|---|---|
| TC-FV10-210 | unit | `check()` with dangerous-statement SQL text → `error_code == SQL_DENY_STATEMENT` (AC-FV10-098). Implemented as `tests/test_simple_guardrail.py::test_guardrail_rejects_dangerous_statement_with_sql_deny_statement`. |
| TC-FV10-211 | unit | `check()` with prose SQL text → `error_code == SQL_DENY_UNRECOGNIZED_OUTPUT` (AC-FV10-099). Implemented as `test_guardrail_rejects_prose_output_with_sql_deny_unrecognized_output`. |

### 8.3 Unit Tests — `api_error_for_warning()`

| ID | Layer | Description |
|---|---|---|
| TC-FV10-212 | unit | `api_error_for_warning(WarningMessage(code=SQL_DENY_UNRECOGNIZED_OUTPUT))` → `SQL_NOT_QUERYABLE` (AC-FV10-100). Implemented as `tests/test_api_models.py::test_api_error_for_warning_maps_unrecognized_output_to_sql_not_queryable`. |
| TC-FV10-213 | regression | `api_error_for_warning()` for `SQL_DENY_STATEMENT`, `SQL_DENY_OBJECT`, `SQL_DENY_FUNCTION` each still return `SQL_GUARDRAIL_BLOCKED` (AC-FV10-101). Implemented as `test_api_error_for_warning_still_maps_guardrail_denials_to_sql_guardrail_blocked` (parametrized). |

### 8.4 Integration Tests — HTTP and Frontend

| ID | Layer | Description |
|---|---|---|
| TC-FV10-214 | integration (HTTP) | `POST /api/v2/chat/query` with an LLM stub returning prose output for a question with no matching schema table returns `code == "SQL_NOT_QUERYABLE"` and HTTP status `400` (AC-FV10-102; the `400` mapping is a §6 correction — see §10). Implemented as `tests/test_v2_chat_query_http.py::test_v2_chat_query_with_non_queryable_model_output_returns_sql_not_queryable`. |
| TC-FV10-215 | frontend | A component/story test asserting the `SQL_NOT_QUERYABLE` branch renders "Can't generate a query for this question," and a sibling test confirming the `SQL_GUARDRAIL_BLOCKED` branch is pixel/text-identical to its pre-spec rendering (AC-FV10-103). **Not implemented as an automated test** — this project has no existing component-level or snapshot test harness for `App.tsx` to extend (its pre-existing `SQL_GUARDRAIL_BLOCKED` branch has none either); see §10 for how AC-FV10-103 was verified instead. |

### 8.5 Regression Tests

| ID | Layer | Description |
|---|---|---|
| TC-FV10-216 | regression | Every pre-existing test in `tests/test_sql_validator.py` covering `EMPTY_SQL`, `MULTIPLE_STATEMENTS`, and `STRUCTURAL_RISK` continues to pass unchanged — these three violation codes and their downstream `ErrorCode`/`ApiErrorCode` mapping are untouched by this spec (NFR-FV10-030). |

## 9. Traceability Matrix

| Requirement | Acceptance Criteria | Test Cases |
|---|---|---|
| FR-FV10-087 | AC-FV10-096, AC-FV10-097 | TC-FV10-208, TC-FV10-209 |
| FR-FV10-088 | AC-FV10-098, AC-FV10-099 | TC-FV10-210, TC-FV10-211 |
| FR-FV10-089 | AC-FV10-100, AC-FV10-101 | TC-FV10-212, TC-FV10-213 |
| FR-FV10-090 | AC-FV10-102, AC-FV10-103 | TC-FV10-214, TC-FV10-215 |
| NFR-FV10-030 | AC-FV10-096, AC-FV10-101 | TC-FV10-208, TC-FV10-213, TC-FV10-216 |

## 10. Implementation Notes

- This spec was written before implementation, and TC-FV10-208 through TC-FV10-214 were confirmed to fail against the pre-implementation code for the expected reason — `UNRECOGNIZED_QUERY_OUTPUT`, `SQL_DENY_UNRECOGNIZED_OUTPUT`, and `SQL_NOT_QUERYABLE` did not yet exist — before §6's changes landed.
- §6.3 removed `SimpleSqlGuardrail._deny(self, trace_id, message)` rather than adding a second method alongside it, since every one of its call sites inside `check()` needed the same `validation.violation_code` dispatch — leaving the old helper in place unused, or partially used, would have reintroduced exactly the kind of silent-collapse risk this spec exists to close. `check()` now has a single call site using `_deny_for_violation()`.
- **§6 as originally written omitted one contract**, found while implementing TC-FV10-214: `status_code_for_envelope()` (`src/chatbi/api/http.py:495-506`) maps `ApiErrorCode` values to HTTP status codes and had no branch for the new `SQL_NOT_QUERYABLE` code, silently falling through to its `return 200` default for a response whose `error` field was non-null. Added `if envelope.code is ApiErrorCode.SQL_NOT_QUERYABLE: return 400`, alongside the pre-existing `SQL_GUARDRAIL_BLOCKED → 403` mapping this function already had — `400` matches the status this file already uses for `REQ_INVALID_ARGUMENT`, another "the request as phrased can't be fulfilled" case rather than a security denial.
- TC-FV10-214's LLM stub reliably produces prose rather than SQL for a schema-mismatched question, per the source design's §2.2 reasoning (an "explain step by step" question against a metric absent from `_SQL_GENERATION_SYSTEM_PROMPT`'s schema): the stub (`_ProseForSqlGenerationLLMClient`) returns prose specifically for `task_type == "sql_generation"` requests and a benign string otherwise, wired through a `SimpleOrchestrator(llm_client=...)`/`ChatBIApplication(orchestrator=...)` passed to `create_app(application=...)` — a deterministic stub, not a live model call, is what makes this test reliable in CI.
- **AC-FV10-103/TC-FV10-215 (the frontend rendering assertion) was not implemented as an automated test.** This project has no existing component-level or snapshot test harness for `frontend/src/App.tsx` — its pre-existing `SQL_GUARDRAIL_BLOCKED` branch (§2.3) has no dedicated test either, only the Python-level `tests/test_frontend_view_models.py`/`tests/test_frontend_evaluation_component_props.py` style tests that assert on unrelated view-model shapes, not rendered JSX text. AC-FV10-103 was instead verified by (a) `npx tsc --noEmit` passing cleanly after the §6.5 JSX addition, confirming no type or syntax regression, and (b) direct code review confirming the new `SQL_NOT_QUERYABLE` branch is a sibling `? :` clause preceding the untouched `SQL_GUARDRAIL_BLOCKED` branch, which is unchanged character-for-character. A future followup could add a lightweight frontend test harness to make this a real automated check — out of scope here, matching the scope this spec's §2 already declared.
