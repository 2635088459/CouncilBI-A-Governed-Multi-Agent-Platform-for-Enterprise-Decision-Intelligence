import pytest

from chatbi.governance import (
    GuardrailDecisionStatus,
    GuardrailDecisionV2,
    GuardrailRequestV2,
    GuardrailRuleCode,
    MaskingInstruction,
    MaskingStrategy,
    RuleHit,
)


def test_guardrail_request_v2_accepts_required_fields() -> None:
    request = GuardrailRequestV2(
        trace_id="tr_12345678",
        user_id="u_001",
        role="business_user",
        sql_text="SELECT * FROM orders",
        semantic_version_id="sem_v1",
    )

    assert request.trace_id == "tr_12345678"
    assert request.role == "business_user"
    assert request.semantic_version_id == "sem_v1"


def test_guardrail_request_v2_rejects_invalid_role() -> None:
    with pytest.raises(ValueError, match="role"):
        GuardrailRequestV2(
            trace_id="tr_12345678",
            user_id="u_001",
            role="owner",  # type: ignore[arg-type]
            sql_text="SELECT * FROM orders",
            semantic_version_id="sem_v1",
        )


def test_guardrail_request_v2_rejects_empty_sql() -> None:
    with pytest.raises(ValueError, match="sql_text length"):
        GuardrailRequestV2(
            trace_id="tr_12345678",
            user_id="u_001",
            role="analyst",
            sql_text=" ",
            semantic_version_id="sem_v1",
        )


def test_allowed_guardrail_decision_v2_requires_rewritten_sql() -> None:
    with pytest.raises(ValueError, match="rewritten_sql"):
        GuardrailDecisionV2(
            decision=GuardrailDecisionStatus.ALLOW,
            rewritten_sql=None,
            sql_hash="abc123",
        )


def test_denied_guardrail_decision_v2_requires_error() -> None:
    with pytest.raises(ValueError, match="error"):
        GuardrailDecisionV2(
            decision=GuardrailDecisionStatus.DENY,
            rewritten_sql=None,
            sql_hash="abc123",
        )


def test_guardrail_decision_v2_carries_rule_hits_and_masking_plan() -> None:
    decision = GuardrailDecisionV2(
        decision=GuardrailDecisionStatus.ALLOW,
        rewritten_sql="SELECT email FROM customers LIMIT 100",
        sql_hash="abc123",
        rule_hits=[
            RuleHit(
                rule_code=GuardrailRuleCode.ROW_LIMIT_REWRITE,
                message="LIMIT 100 was added.",
            )
        ],
        masking_plan=[
            MaskingInstruction(
                field_name="customers.email",
                strategy=MaskingStrategy.REDACT,
                reason="Email is protected by masking policy.",
            )
        ],
    )

    assert decision.decision is GuardrailDecisionStatus.ALLOW
    assert decision.rule_hits[0].rule_code is GuardrailRuleCode.ROW_LIMIT_REWRITE
    assert decision.masking_plan[0].strategy is MaskingStrategy.REDACT


def test_denied_guardrail_decision_v2_rejects_rewritten_sql() -> None:
    with pytest.raises(ValueError, match="rewritten_sql"):
        GuardrailDecisionV2(
            decision=GuardrailDecisionStatus.DENY,
            rewritten_sql="SELECT * FROM orders LIMIT 100",
            sql_hash="abc123",
            error={
                "code": "SQL_DENIED_WRITE_OPERATION",
                "message": "Write statements are not allowed.",
                "retryable": False,
            },
        )
