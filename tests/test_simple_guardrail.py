from chatbi.core.contracts import (
    ErrorCode,
    GuardrailDecision,
    Locale,
    QueryRequest,
    UserRole,
    new_trace_id,
)
from chatbi.governance.simple_guardrail import SimpleSqlGuardrail


def make_request() -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question="Show revenue trend.",
        locale=Locale.EN,
        role=UserRole.BUSINESS_USER,
    )


def test_guardrail_allows_single_select_statement() -> None:
    result = SimpleSqlGuardrail().check(
        "SELECT month, revenue FROM revenue_by_month",
        make_request(),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.ALLOW
    assert result.safe_sql == "SELECT month, revenue FROM revenue_by_month"
    assert result.error_code is None


def test_guardrail_normalizes_allowed_select_statement() -> None:
    result = SimpleSqlGuardrail().check(
        "  SELECT   month,   revenue   FROM   revenue_by_month  ",
        make_request(),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.ALLOW
    assert result.safe_sql == "SELECT month, revenue FROM revenue_by_month"


def test_guardrail_rejects_drop_table_statement() -> None:
    result = SimpleSqlGuardrail().check(
        "DROP TABLE orders",
        make_request(),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_STATEMENT


def test_guardrail_rejects_delete_statement() -> None:
    result = SimpleSqlGuardrail().check(
        "DELETE FROM orders",
        make_request(),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_STATEMENT


def test_guardrail_rejects_multiple_statements() -> None:
    result = SimpleSqlGuardrail().check(
        "SELECT * FROM orders; DROP TABLE orders",
        make_request(),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_STATEMENT


def test_guardrail_rejects_empty_sql() -> None:
    result = SimpleSqlGuardrail().check(
        " ",
        make_request(),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_STATEMENT
