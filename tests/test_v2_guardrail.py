from dataclasses import fields

import pytest

from chatbi.governance import (
    GuardrailDecisionStatus,
    GuardrailRequestV2,
    GuardrailRuleCode,
    InMemoryGuardrailAuditLogV2,
    SimpleSqlGuardrailV2,
)


def make_request(sql_text: str, role: str = "business_user") -> GuardrailRequestV2:
    return GuardrailRequestV2(
        trace_id="tr_12345678",
        user_id="u_001",
        role=role,  # type: ignore[arg-type]
        sql_text=sql_text,
        semantic_version_id="sem_v1",
    )


def test_v2_guardrail_allows_select_and_rewrites_missing_limit() -> None:
    decision = SimpleSqlGuardrailV2().check(
        make_request("SELECT month, revenue FROM revenue_by_month")
    )

    assert decision.decision is GuardrailDecisionStatus.ALLOW
    assert decision.rewritten_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert len(decision.sql_hash) == 64
    assert decision.error is None
    assert [hit.rule_code for hit in decision.rule_hits] == [GuardrailRuleCode.ROW_LIMIT_REWRITE]


def test_v2_guardrail_caps_existing_limit_above_configured_max_rows() -> None:
    decision = SimpleSqlGuardrailV2().check(
        make_request("SELECT month, revenue FROM revenue_by_month LIMIT 10000")
    )

    assert decision.decision is GuardrailDecisionStatus.ALLOW
    assert decision.rewritten_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert [hit.rule_code for hit in decision.rule_hits] == [GuardrailRuleCode.ROW_LIMIT_REWRITE]


def test_v2_guardrail_denies_drop_with_structured_error() -> None:
    decision = SimpleSqlGuardrailV2().check(make_request("DROP TABLE orders"))

    assert decision.decision is GuardrailDecisionStatus.DENY
    assert decision.rewritten_sql is None
    assert len(decision.sql_hash) == 64
    assert decision.error is not None
    assert decision.error["code"] == "SQL_DENIED_WRITE_OPERATION"
    assert decision.rule_hits[0].rule_code is GuardrailRuleCode.WRITE_OPERATION


@pytest.mark.parametrize(
    "sql_text",
    [
        "DROP TABLE orders",
        "DELETE FROM orders",
        "UPDATE orders SET revenue = 0",
        "INSERT INTO orders(order_id) VALUES (1)",
        "ALTER TABLE orders ADD COLUMN probe int",
        "TRUNCATE TABLE orders",
    ],
)
def test_v2_guardrail_denies_dangerous_sql_fixture_set(sql_text: str) -> None:
    decision = SimpleSqlGuardrailV2().check(make_request(sql_text))

    assert decision.decision is GuardrailDecisionStatus.DENY
    assert decision.rewritten_sql is None
    assert decision.error is not None
    assert decision.error["code"] == "SQL_DENIED_WRITE_OPERATION"
    assert decision.rule_hits[0].rule_code is GuardrailRuleCode.WRITE_OPERATION


def test_v2_guardrail_denies_restricted_column_as_unauthorized_object() -> None:
    decision = SimpleSqlGuardrailV2().check(
        make_request("SELECT orders.user_id FROM orders")
    )

    assert decision.decision is GuardrailDecisionStatus.DENY
    assert decision.error is not None
    assert decision.error["code"] == "SQL_DENIED_OBJECT"
    assert decision.rule_hits[0].rule_code is GuardrailRuleCode.UNAUTHORIZED_OBJECT


def test_v2_guardrail_returns_masking_plan_for_p1_field() -> None:
    decision = SimpleSqlGuardrailV2().check(
        make_request("SELECT customers.user_email FROM customers LIMIT 25", role="analyst")
    )

    assert decision.decision is GuardrailDecisionStatus.ALLOW
    assert decision.rewritten_sql == "SELECT customers.user_email FROM customers LIMIT 25"
    assert decision.error is None
    assert len(decision.masking_plan) == 1
    assert decision.masking_plan[0].field_name == "customers.user_email"
    assert decision.masking_plan[0].strategy.value == "partial"
    assert [hit.rule_code for hit in decision.rule_hits] == [GuardrailRuleCode.MASKING_REQUIRED]
    assert decision.rule_hits[0].object_name == "customers.user_email"


def test_v2_guardrail_detects_multiple_statements() -> None:
    decision = SimpleSqlGuardrailV2().check(
        make_request("SELECT * FROM orders; DROP TABLE orders")
    )

    assert decision.decision is GuardrailDecisionStatus.DENY
    assert decision.error is not None
    assert decision.error["code"] == "SQL_DENIED_WRITE_OPERATION"
    assert decision.rule_hits[0].rule_code is GuardrailRuleCode.MULTIPLE_STATEMENTS


def test_v2_guardrail_writes_audit_record_for_allow_decision() -> None:
    audit_log = InMemoryGuardrailAuditLogV2()
    request = make_request("SELECT month, revenue FROM revenue_by_month")

    decision = SimpleSqlGuardrailV2(audit_log=audit_log).check(request)
    record = audit_log.get_v2(request.trace_id)

    assert decision.decision is GuardrailDecisionStatus.ALLOW
    assert record is not None
    assert record.audit_event_id.startswith("aud_")
    assert record.trace_id == request.trace_id
    assert record.user_id == request.user_id
    assert record.role == request.role
    assert record.sql_hash == decision.sql_hash
    assert record.decision is GuardrailDecisionStatus.ALLOW
    assert [hit.rule_code for hit in record.rule_hits] == [GuardrailRuleCode.ROW_LIMIT_REWRITE]
    assert record.latency_ms >= 0


def test_v2_guardrail_audit_record_does_not_store_plaintext_credentials_or_sql() -> None:
    audit_log = InMemoryGuardrailAuditLogV2()
    secret_database_url = "postgresql://chatbi:super_secret@db:5432/chatbi"
    request = make_request(f"SELECT '{secret_database_url}' AS leaked_value FROM orders")

    decision = SimpleSqlGuardrailV2(audit_log=audit_log).check(request)
    record = audit_log.get_v2(request.trace_id)

    assert decision.decision is GuardrailDecisionStatus.ALLOW
    assert record is not None
    record_field_names = {field.name for field in fields(record)}
    assert "sql_hash" in record_field_names
    assert "sql_text" not in record_field_names
    assert "original_sql" not in record_field_names
    assert "rewritten_sql" not in record_field_names
    assert "database_url" not in record_field_names
    assert "password" not in record_field_names
    assert secret_database_url not in repr(record)
    assert "super_secret" not in repr(record)


def test_v2_guardrail_writes_audit_record_for_deny_decision() -> None:
    audit_log = InMemoryGuardrailAuditLogV2()
    request = make_request("DROP TABLE orders")

    decision = SimpleSqlGuardrailV2(audit_log=audit_log).check(request)
    record = audit_log.get_v2(request.trace_id)

    assert decision.decision is GuardrailDecisionStatus.DENY
    assert record is not None
    assert record.trace_id == request.trace_id
    assert record.sql_hash == decision.sql_hash
    assert record.decision is GuardrailDecisionStatus.DENY
    assert [hit.rule_code for hit in record.rule_hits] == [GuardrailRuleCode.WRITE_OPERATION]
    assert record.latency_ms >= 0
