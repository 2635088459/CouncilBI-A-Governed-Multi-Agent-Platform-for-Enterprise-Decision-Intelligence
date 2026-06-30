from chatbi.core.contracts import ErrorCode, GuardrailDecision, GuardrailResult
from chatbi.governance import (
    GuardrailDecisionStatus,
    GuardrailDecisionV2Builder,
    GuardrailRuleCode,
)


def test_decision_v2_builder_builds_allow_decision_with_rewrite_hit() -> None:
    decision = GuardrailDecisionV2Builder().build(
        sql_text="SELECT month, revenue FROM revenue_by_month",
        legacy_result=GuardrailResult(
            decision=GuardrailDecision.ALLOW,
            trace_id="tr_12345678",
            safe_sql="SELECT month, revenue FROM revenue_by_month LIMIT 100",
        ),
    )

    assert decision.decision is GuardrailDecisionStatus.ALLOW
    assert decision.rewritten_sql == "SELECT month, revenue FROM revenue_by_month LIMIT 100"
    assert len(decision.sql_hash) == 64
    assert [hit.rule_code for hit in decision.rule_hits] == [
        GuardrailRuleCode.ROW_LIMIT_REWRITE
    ]
    assert decision.masking_plan == []
    assert decision.error is None


def test_decision_v2_builder_builds_allow_decision_with_masking_plan() -> None:
    decision = GuardrailDecisionV2Builder().build(
        sql_text="SELECT customers.user_email FROM customers LIMIT 25",
        legacy_result=GuardrailResult(
            decision=GuardrailDecision.ALLOW,
            trace_id="tr_12345678",
            safe_sql="SELECT customers.user_email FROM customers LIMIT 25",
        ),
    )

    assert decision.decision is GuardrailDecisionStatus.ALLOW
    assert [instruction.field_name for instruction in decision.masking_plan] == [
        "customers.user_email"
    ]
    assert [hit.rule_code for hit in decision.rule_hits] == [
        GuardrailRuleCode.MASKING_REQUIRED
    ]


def test_decision_v2_builder_builds_denial_decision_with_error_payload() -> None:
    decision = GuardrailDecisionV2Builder().build(
        sql_text="DROP TABLE orders",
        legacy_result=GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id="tr_12345678",
            error_code=ErrorCode.SQL_DENY_STATEMENT,
            message="Only SELECT statements are allowed.",
        ),
    )

    assert decision.decision is GuardrailDecisionStatus.DENY
    assert decision.rewritten_sql is None
    assert decision.masking_plan == []
    assert [hit.rule_code for hit in decision.rule_hits] == [
        GuardrailRuleCode.WRITE_OPERATION
    ]
    assert decision.error == {
        "code": "SQL_DENIED_WRITE_OPERATION",
        "message": "Only SELECT statements are allowed.",
        "retryable": False,
    }


def test_decision_v2_builder_builds_object_denial_rule_hit() -> None:
    decision = GuardrailDecisionV2Builder().build(
        sql_text="SELECT orders.user_id FROM orders",
        legacy_result=GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id="tr_12345678",
            error_code=ErrorCode.SQL_DENY_OBJECT,
            message="Role business_user is not allowed to query column orders.user_id.",
        ),
    )

    assert [hit.rule_code for hit in decision.rule_hits] == [
        GuardrailRuleCode.UNAUTHORIZED_OBJECT
    ]
    assert decision.error is not None
    assert decision.error["code"] == "SQL_DENIED_OBJECT"
