import pytest

from chatbi.core.contracts import (
    ErrorCode,
    GuardrailDecision,
    Locale,
    QueryRequest,
    UserRole,
    new_trace_id,
)
from chatbi.governance.audit import InMemoryGuardrailAuditLog
from chatbi.governance.simple_guardrail import SimpleSqlGuardrail


def make_request(role: UserRole = UserRole.BUSINESS_USER) -> QueryRequest:
    return QueryRequest(
        user_id="u_001",
        session_id="s_001",
        question="Show revenue trend.",
        locale=Locale.EN,
        role=role,
    )


def test_guardrail_allows_single_select_statement() -> None:
    result = SimpleSqlGuardrail().check(
        "SELECT month, revenue FROM revenue_by_month",
        make_request(),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.ALLOW
    assert result.safe_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert result.error_code is None


def test_guardrail_normalizes_allowed_select_statement() -> None:
    result = SimpleSqlGuardrail().check(
        "  SELECT   month,   revenue   FROM   revenue_by_month  ",
        make_request(),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.ALLOW
    assert result.safe_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 100"


def test_guardrail_keeps_existing_limit() -> None:
    result = SimpleSqlGuardrail().check(
        "SELECT month, revenue FROM revenue_by_month LIMIT 25",
        make_request(),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.ALLOW
    assert result.safe_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 25"


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


@pytest.mark.parametrize(
    "sql_text",
    (
        "SELECT * FROM orders WHERE status = 'paid' -- ignore rest",
        "SELECT * FROM orders WHERE status = 'paid' # ignore rest",
        "SELECT * FROM orders /* hidden condition */",
        "SELECT * FROM orders WHERE status = 'paid' */",
        "SELECT * FROM orders UNION SELECT * FROM users",
        "SELECT * FROM orders union all SELECT * FROM users",
        "SELECT * FROM orders WHERE id = 1 OR 1 = 1",
        "SELECT * FROM orders WHERE id = 1 or 'a' = 'a'",
        'SELECT * FROM orders WHERE id = 1 OR "x" = "x"',
        "SELECT * FROM orders WHERE id = 1 AND 2 = 2",
        "SELECT * FROM orders WHERE status = 'paid' OR paid = paid",
        "SELECT * FROM orders WHERE id = 1 OR 0001 = 0001",
        "SELECT * FROM orders WHERE id = 1; SELECT * FROM users",
        "SELECT * FROM orders; DELETE FROM orders",
        "SELECT * FROM orders WHERE id = 1; --",
        "SELECT * FROM orders WHERE id = 1 OR 1=1",
        "SELECT * FROM orders WHERE id = 1 AND '1'='1'",
        "SELECT sleep(5) FROM orders",
        "SELECT benchmark(1000000, md5('x')) FROM orders",
        "SELECT load_file('/etc/passwd') FROM orders",
    ),
)
def test_guardrail_blocks_sql_injection_variants(sql_text: str) -> None:
    result = SimpleSqlGuardrail().check(
        sql_text,
        make_request(),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_STATEMENT


def test_guardrail_denies_restricted_table_for_business_user() -> None:
    result = SimpleSqlGuardrail().check(
        "SELECT user_id FROM users",
        make_request(role=UserRole.BUSINESS_USER),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_OBJECT
    assert result.message is not None
    assert "business_user" in result.message
    assert "users" in result.message


def test_guardrail_denies_restricted_column_for_business_user() -> None:
    result = SimpleSqlGuardrail().check(
        "SELECT orders.user_id FROM orders",
        make_request(role=UserRole.BUSINESS_USER),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_OBJECT
    assert result.message is not None
    assert "orders.user_id" in result.message


def test_guardrail_allows_restricted_column_for_analyst() -> None:
    result = SimpleSqlGuardrail().check(
        "SELECT orders.user_id FROM orders",
        make_request(role=UserRole.ANALYST),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.ALLOW
    assert result.safe_sql == "SELECT orders.user_id FROM orders LIMIT 100"


def test_guardrail_denies_p0_field_from_data_model_catalog() -> None:
    result = SimpleSqlGuardrail().check(
        "SELECT customers.customer_id FROM customers",
        make_request(role=UserRole.ANALYST),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_OBJECT
    assert result.message is not None
    assert "P0 field customers.customer_id" in result.message


def test_guardrail_denies_unqualified_p0_field_when_table_is_known() -> None:
    result = SimpleSqlGuardrail().check(
        "SELECT customer_id FROM orders",
        make_request(role=UserRole.ANALYST),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_OBJECT
    assert result.message is not None
    assert "P0 field orders.customer_id" in result.message


def test_guardrail_allows_non_p0_business_field_from_data_model_catalog() -> None:
    result = SimpleSqlGuardrail().check(
        "SELECT order_amount FROM orders",
        make_request(role=UserRole.ANALYST),
        new_trace_id(),
    )

    assert result.decision is GuardrailDecision.ALLOW
    assert result.safe_sql == "SELECT order_amount FROM orders LIMIT 100"


def test_guardrail_writes_audit_record_for_allow_decision() -> None:
    audit_log = InMemoryGuardrailAuditLog()
    trace_id = new_trace_id()

    result = SimpleSqlGuardrail(audit_log=audit_log).check(
        "SELECT month, revenue FROM revenue_by_month",
        make_request(),
        trace_id,
    )
    record = audit_log.get(trace_id)

    assert result.decision is GuardrailDecision.ALLOW
    assert record is not None
    assert record.audit_event_id.startswith("aud_")
    assert record.trace_id == trace_id
    assert record.user_id == "u_001"
    assert record.role is UserRole.BUSINESS_USER
    assert record.original_sql == "SELECT month, revenue FROM revenue_by_month"
    assert record.safe_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert record.decision is GuardrailDecision.ALLOW
    assert record.error_code is None


def test_guardrail_writes_audit_record_for_deny_decision() -> None:
    audit_log = InMemoryGuardrailAuditLog()
    trace_id = new_trace_id()

    result = SimpleSqlGuardrail(audit_log=audit_log).check(
        "DROP TABLE orders",
        make_request(),
        trace_id,
    )
    record = audit_log.get(trace_id)

    assert result.decision is GuardrailDecision.DENY
    assert record is not None
    assert record.trace_id == trace_id
    assert record.original_sql == "DROP TABLE orders"
    assert record.safe_sql is None
    assert record.decision is GuardrailDecision.DENY
    assert record.error_code is ErrorCode.SQL_DENY_STATEMENT
    assert record.message == "Only SELECT statements are allowed."


def test_guardrail_audit_log_replays_original_sql_and_decision_by_trace_id() -> None:
    audit_log = InMemoryGuardrailAuditLog()
    trace_id = new_trace_id()

    SimpleSqlGuardrail(audit_log=audit_log).check(
        "SELECT orders.user_id FROM orders",
        make_request(role=UserRole.BUSINESS_USER),
        trace_id,
    )
    replayed_record = audit_log.get(trace_id)

    assert replayed_record is not None
    assert replayed_record.original_sql == "SELECT orders.user_id FROM orders"
    assert replayed_record.decision is GuardrailDecision.DENY
    assert replayed_record.error_code is ErrorCode.SQL_DENY_OBJECT


def test_guardrail_audit_log_keeps_multiple_events_for_same_trace_id() -> None:
    audit_log = InMemoryGuardrailAuditLog()
    trace_id = new_trace_id()
    guardrail = SimpleSqlGuardrail(audit_log=audit_log, timeout_ms=1_000)

    first_result = guardrail.check(
        "SELECT month, revenue FROM revenue_by_month",
        make_request(),
        trace_id,
    )
    second_result = guardrail.check_timeout(
        elapsed_ms=1_200,
        sql_text=first_result.safe_sql or "",
        request=make_request(),
        trace_id=trace_id,
    )
    records = audit_log.list_by_trace_id(trace_id)

    assert first_result.decision is GuardrailDecision.ALLOW
    assert second_result is not None
    assert second_result.decision is GuardrailDecision.DENY
    assert len(records) == 2
    assert records[0].decision is GuardrailDecision.ALLOW
    assert records[1].error_code is ErrorCode.SQL_DENY_TIMEOUT
    assert audit_log.get(trace_id) == records[1]


def test_guardrail_allows_runtime_when_elapsed_time_is_within_timeout() -> None:
    result = SimpleSqlGuardrail(timeout_ms=1_000).check_timeout(
        elapsed_ms=800,
        sql_text="SELECT month, revenue FROM revenue_by_month",
        request=make_request(),
        trace_id=new_trace_id(),
    )

    assert result is None


def test_guardrail_denies_runtime_when_query_exceeds_timeout() -> None:
    result = SimpleSqlGuardrail(timeout_ms=1_000).check_timeout(
        elapsed_ms=1_200,
        sql_text="SELECT month, revenue FROM revenue_by_month",
        request=make_request(),
        trace_id=new_trace_id(),
    )

    assert result is not None
    assert result.decision is GuardrailDecision.DENY
    assert result.error_code is ErrorCode.SQL_DENY_TIMEOUT
    assert result.message is not None
    assert "1000ms" in result.message
    assert "1200ms" in result.message


def test_guardrail_writes_audit_record_for_timeout_denial() -> None:
    audit_log = InMemoryGuardrailAuditLog()
    trace_id = new_trace_id()

    result = SimpleSqlGuardrail(
        timeout_ms=1_000,
        audit_log=audit_log,
    ).check_timeout(
        elapsed_ms=1_200,
        sql_text="SELECT month, revenue FROM revenue_by_month",
        request=make_request(),
        trace_id=trace_id,
    )
    record = audit_log.get(trace_id)

    assert result is not None
    assert result.error_code is ErrorCode.SQL_DENY_TIMEOUT
    assert record is not None
    assert record.original_sql == "SELECT month, revenue FROM revenue_by_month"
    assert record.decision is GuardrailDecision.DENY
    assert record.error_code is ErrorCode.SQL_DENY_TIMEOUT
