# 10.13 Guardrail Deny-Reason Preservation for Non-SELECT LLM Output

中文版：[../../zh-CN/10-followups/13-guardrail-deny-reason-preservation.zh-CN.md](../../zh-CN/10-followups/13-guardrail-deny-reason-preservation.zh-CN.md)

## 1. Problem Observed

An analyst asked: *"Explain, step by step, how you calculated the churn rate for the enterprise segment in March 2026, including which tables/columns you pulled from — I need to include this in an audit trail."*

The response was blocked with:

> **Query blocked — data modifications are not permitted**
> ChatBI is a read-only analytics platform. Requests to insert, update, delete, or otherwise modify data are automatically rejected by the security guardrail. If you have a legitimate data correction request, contact your data team directly.

This is a pure read/explain request. It contains no write intent whatsoever — there is nothing to "correct." The message actively misinforms the analyst about what happened and what to do about it: there is no data-modification issue to take to a data team; the real problem, as this document's investigation shows, is that no `churn` table exists anywhere in this orchestrator's schema, and the question asks for a methodology narrative rather than a specific number.

## 2. What Already Exists

### 2.1 Where the block actually happens

The question passes `_is_supported_question()` (`src/chatbi/orchestration/simple_orchestrator.py:822-854`) — it matches on "explain," among other supported phrasings — so it is not rejected before an SQL-generation attempt. The block happens **after** the LLM has already produced its output, when that output is checked by `SqlStatementValidator.validate()` (`src/chatbi/governance/sql_validator.py:57-95`):

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
        SqlValidationViolationCode.NON_SELECT_STATEMENT,
        "Only SELECT statements are allowed.",
    )
```

Both branches return the identical `SqlValidationViolationCode.NON_SELECT_STATEMENT` — one for a genuine `DROP`/`DELETE`/`UPDATE`/`INSERT`/`ALTER`/`TRUNCATE` keyword match (`_DANGEROUS_STATEMENT_PATTERN`, `sql_validator.py:10-13` — real write intent, however unlikely from a read-only prompt), the other for **any** text that simply doesn't start with `"select "` or `"with "` — which is what a model produces when it answers in prose instead of SQL. Nothing downstream of this function can tell these two cases apart; the distinction is lost the moment `validate()` returns.

### 2.2 Why this specific question is very likely to hit the second branch, not the first

`_SQL_GENERATION_SYSTEM_PROMPT` (`simple_orchestrator.py:75-89`), the schema-aware fallback used whenever the question isn't matched by one of `_build_sql_candidate`'s hardcoded shortcuts, only describes two tables:

```python
"Available tables:\n"
"revenue_by_month(month VARCHAR, revenue NUMERIC)\n"
"support_ticket_summary(month VARCHAR, product VARCHAR, severity VARCHAR, "
"ticket_count INTEGER, avg_resolution_hours NUMERIC)"
```

There is no `churn` table, no `enterprise_segment` column, nothing resembling a churn-rate metric anywhere in this schema. Asked to "explain, step by step" a calculation over data it cannot see, and told explicitly to reply with "exactly one read-only SQL statement and nothing else," a model has no correct SQL to write — the comment already present at `simple_orchestrator.py:58-63` documents exactly this failure mode for a related case: *"a real GPT model observed to do so wrapped its guess in prose and a markdown fence instead of bare SQL."* An explanatory "step by step" question, on a metric with no matching table, is if anything more likely to produce prose than a request for a specific number would be.

### 2.3 How the distinction is lost twice more downstream

Even where `validate()` returns a violation code, `SimpleSqlGuardrail._deny()` (`src/chatbi/governance/simple_guardrail.py:94-100`) throws it away and always emits one `ErrorCode`:

```python
def _deny(self, trace_id: str, message: str) -> GuardrailResult:
    return GuardrailResult(
        decision=GuardrailDecision.DENY,
        trace_id=trace_id,
        error_code=ErrorCode.SQL_DENY_STATEMENT,
        message=message,
    )
```

Every one of `SqlValidationViolationCode`'s four values — `EMPTY_SQL`, `MULTIPLE_STATEMENTS`, `STRUCTURAL_RISK`, `NON_SELECT_STATEMENT` — collapses into the same `ErrorCode.SQL_DENY_STATEMENT`, distinguishable only by the free-text `message` string, which nothing in the API layer reads.

`api_error_for_warning()` (`src/chatbi/api/models.py:340-346`) then collapses a third time:

```python
def api_error_for_warning(warning: WarningMessage) -> ApiErrorCode:
    if warning.code in {
        ErrorCode.SQL_DENY_STATEMENT,
        ErrorCode.SQL_DENY_OBJECT,
        ErrorCode.SQL_DENY_FUNCTION,
    }:
        return ApiErrorCode.SQL_GUARDRAIL_BLOCKED
    ...
```

By the time this reaches the frontend, `SQL_DENY_STATEMENT` (this question's actual path), `SQL_DENY_OBJECT` (a disallowed table), and `SQL_DENY_FUNCTION` (a disallowed SQL function) are all indistinguishable — one API error code, `SQL_GUARDRAIL_BLOCKED`, for three structurally different reasons.

The frontend (`frontend/src/App.tsx:1143-1154`) then hardcodes one message for that one code:

```tsx
errorCode === "SQL_GUARDRAIL_BLOCKED" ? (
  <div className="answer-blocked">
    <div className="blocked-icon">⊘</div>
    <div className="blocked-body">
      <p className="blocked-title">Query blocked — data modifications are not permitted</p>
      <p className="blocked-desc">
        ChatBI is a read-only analytics platform. Requests to insert, update, delete,
        or otherwise modify data are automatically rejected by the security guardrail.
        If you have a legitimate data correction request, contact your data team directly.
      </p>
    </div>
  </div>
```

This message is accurate for a real `_DANGEROUS_STATEMENT_PATTERN` hit. For this question's actual, far more likely path — the model answered in prose because no churn table exists to query — it is simply wrong: there was no modification attempt, and "contact your data team" sends the analyst toward the wrong fix entirely.

## 3. Design: Split "Wrote a Real Statement" From "Didn't Write a Query at All"

The two branches conflated in §2.1 are genuinely different failure modes and are given genuinely different `SqlValidationViolationCode` values:

```python
class SqlValidationViolationCode(StrEnum):
    EMPTY_SQL = "empty_sql"
    MULTIPLE_STATEMENTS = "multiple_statements"
    STRUCTURAL_RISK = "structural_risk"
    NON_SELECT_STATEMENT = "non_select_statement"       # unchanged: a real DML/DDL keyword was found
    UNRECOGNIZED_QUERY_OUTPUT = "unrecognized_query_output"  # new: no SELECT/WITH prefix, and no dangerous keyword either
```

`SqlStatementValidator.validate()`'s two checks are unchanged in what they test, only in what they report:

```python
if _DANGEROUS_STATEMENT_PATTERN.search(normalized_sql):
    return self._deny(
        normalized_sql,
        SqlValidationViolationCode.NON_SELECT_STATEMENT,   # unchanged — real write intent
        "Only SELECT statements are allowed.",
    )

if not normalized_sql.lower().startswith(_ALLOWED_STATEMENT_PREFIXES):
    return self._deny(
        normalized_sql,
        SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT,  # new
        "The model's output was not a single read-only query.",
    )
```

## 4. Design: Thread the Distinction Through Two More Layers

`ErrorCode` (`src/chatbi/core/contracts.py`) gains one new value, `SQL_DENY_UNRECOGNIZED_OUTPUT`, alongside the existing `SQL_DENY_STATEMENT`/`SQL_DENY_OBJECT`/`SQL_DENY_FUNCTION`. `SimpleSqlGuardrail._deny()` is split so the caller — which already has the `SqlValidationResult` and its `violation_code` — chooses the right `ErrorCode` instead of `_deny()` hardcoding one:

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

`api_error_for_warning()` (`src/chatbi/api/models.py:340-346`) gains a matching branch, mapping to a new `ApiErrorCode.SQL_NOT_QUERYABLE` kept distinct from `SQL_GUARDRAIL_BLOCKED`:

```python
def api_error_for_warning(warning: WarningMessage) -> ApiErrorCode:
    if warning.code is ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT:
        return ApiErrorCode.SQL_NOT_QUERYABLE
    if warning.code in {
        ErrorCode.SQL_DENY_STATEMENT,
        ErrorCode.SQL_DENY_OBJECT,
        ErrorCode.SQL_DENY_FUNCTION,
    }:
        return ApiErrorCode.SQL_GUARDRAIL_BLOCKED
    ...
```

The frontend (`frontend/src/App.tsx:1143-1154`) gains a sibling branch for `SQL_NOT_QUERYABLE`, with copy that describes what actually happened instead of implying a write attempt:

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
  ...
```

For the reported question, the analyst now sees a message that correctly identifies the actual gap (no matching table/metric, or a question shape the read-only generator can't turn into SQL) instead of being told to contact a data team about a data-modification request that never happened.

## 5. Verification

[Spec FV10.13](../../../../spec/final-version/en/10-followups/13-guardrail-deny-reason-preservation.spec.en.md) turned §3 and §4 into requirements, acceptance criteria, and tests before implementation. In outline:

- Unit tests for `SqlStatementValidator.validate()` (`tests/test_sql_validator.py`): a `_DANGEROUS_STATEMENT_PATTERN` match (e.g. `"UPDATE revenue_by_month SET revenue = 0"`) still returns `NON_SELECT_STATEMENT`; prose with no SELECT/WITH prefix and no dangerous keyword (e.g. `"I don't have a churn table to query."`) returns the new `UNRECOGNIZED_QUERY_OUTPUT`.
- Unit tests for `SimpleSqlGuardrail.check()` (`tests/test_simple_guardrail.py`): each of the two violation codes above produces the correct, distinct `ErrorCode`.
- Unit tests for `api_error_for_warning()` (`tests/test_api_models.py`): `SQL_DENY_UNRECOGNIZED_OUTPUT` maps to `SQL_NOT_QUERYABLE`; the three pre-existing codes still map to `SQL_GUARDRAIL_BLOCKED` unchanged.
- An HTTP-level test (`tests/test_v2_chat_query_http.py`) driving an LLM stub to prose output for a schema-mismatched question, asserting the response's `code` is `SQL_NOT_QUERYABLE`. This surfaced one contract not originally listed in the spec's data contracts: `status_code_for_envelope()` (`http.py:495-506`) had no branch for the new code at all, silently falling through to `200` for a request whose `error` field was non-null — corrected to `400`, the same status `REQ_INVALID_ARGUMENT` already uses, alongside the existing `SQL_GUARDRAIL_BLOCKED → 403`.
- The full project test suite (1396 tests, excluding the pre-existing Postgres-credential and frontend-bundle failures this project's own convention already documents as unrelated) passes.

## 6. Known Limitations — Intentionally Not Addressed Here

- **`EMPTY_SQL`, `MULTIPLE_STATEMENTS`, and `STRUCTURAL_RISK` are left mapped to `SQL_DENY_STATEMENT`/`SQL_GUARDRAIL_BLOCKED` unchanged.** None of these three is what the reported question actually hit, and none of them carries the same specific "sounds like a write" wording problem the `NON_SELECT_STATEMENT`-vs-prose conflation did — the existing DML-flavored message is imprecise but not actively backwards for them the way it was here. Splitting all four codes out individually is a larger, separately-scoped refactor.
- **This does not make SQL generation succeed for questions with no matching table.** A churn-rate question still can't be answered — this design only makes the *reported reason why* accurate. Actually answering it would require extending `_SQL_GENERATION_SYSTEM_PROMPT`'s schema (out of scope; a real churn table/view would need to exist first) or a distinct "I don't have this data" response path, neither of which this document proposes.
- **The new frontend copy is generic.** It does not attempt to tell the analyst *which* table or metric is missing — `SqlValidationResult.message` at this layer has no schema-awareness to draw on. A more specific message would require passing schema-gap information forward from wherever SQL generation actually failed, a larger change than this spec's scope.

## 7. Requirement IDs

| ID | Requirement | Status |
|---|---|---|
| FR-FV10-087 | `SqlStatementValidator.validate()` MUST return a new `SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT` when the normalized SQL text does not start with an allowed statement prefix AND does not match `_DANGEROUS_STATEMENT_PATTERN`; it MUST continue returning `NON_SELECT_STATEMENT` when `_DANGEROUS_STATEMENT_PATTERN` matches. | Implemented |
| FR-FV10-088 | `SimpleSqlGuardrail.check()` MUST map `SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT` to a new `ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT`, distinct from `ErrorCode.SQL_DENY_STATEMENT`. | Implemented |
| FR-FV10-089 | `api_error_for_warning()` MUST map `ErrorCode.SQL_DENY_UNRECOGNIZED_OUTPUT` to a new `ApiErrorCode.SQL_NOT_QUERYABLE`, distinct from `ApiErrorCode.SQL_GUARDRAIL_BLOCKED`. | Implemented |
| FR-FV10-090 | The frontend MUST render a distinct message for `SQL_NOT_QUERYABLE` that does not characterize the request as a data-modification attempt. | Implemented |
| NFR-FV10-030 | This change MUST NOT alter the `ErrorCode`/`ApiErrorCode`/frontend message produced for a genuine `_DANGEROUS_STATEMENT_PATTERN` match, an `SQL_DENY_OBJECT` denial, or an `SQL_DENY_FUNCTION` denial. | Implemented |

## 8. Status: Fixed and Verified

Found via direct code reading of the validation → guardrail → API-error → frontend chain this question's response actually traversed, confirming the information loss at each of the three collapsing points (§2.1, §2.3) rather than relying on a single live reproduction. Written spec-first, per this project's usual SDD+TDD order: [Spec FV10.13](../../../../spec/final-version/en/10-followups/13-guardrail-deny-reason-preservation.spec.en.md) formalized §3 and §4 above into requirements, acceptance criteria, and a test plan, then both were implemented. Fixed in `src/chatbi/governance/sql_validator.py`, `src/chatbi/governance/simple_guardrail.py`, `src/chatbi/core/contracts.py`, `src/chatbi/api/models.py`, `src/chatbi/api/http.py` (§5's `status_code_for_envelope()` addition), and `frontend/src/App.tsx`; covered by new tests in `tests/test_sql_validator.py`, `tests/test_simple_guardrail.py`, `tests/test_api_models.py`, and `tests/test_v2_chat_query_http.py`.
