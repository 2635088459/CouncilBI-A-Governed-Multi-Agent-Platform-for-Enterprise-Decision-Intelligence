from chatbi.core.contracts import ErrorCode
from chatbi.governance import (
    GuardrailRuleCode,
    GuardrailRuleHitBuilder,
    MaskingInstruction,
    MaskingStrategy,
)


def test_rule_hit_builder_reports_row_limit_rewrite() -> None:
    hits = GuardrailRuleHitBuilder().allow_rule_hits(
        original_sql="SELECT month, revenue FROM revenue_by_month",
        rewritten_sql="SELECT month, revenue FROM revenue_by_month LIMIT 100",
        masking_plan=[],
    )

    assert [hit.rule_code for hit in hits] == [GuardrailRuleCode.ROW_LIMIT_REWRITE]
    assert hits[0].message == "A row limit was added to the SQL."


def test_rule_hit_builder_skips_row_limit_when_sql_is_unchanged() -> None:
    hits = GuardrailRuleHitBuilder().allow_rule_hits(
        original_sql="SELECT month, revenue FROM revenue_by_month LIMIT 25",
        rewritten_sql="SELECT month, revenue FROM revenue_by_month LIMIT 25",
        masking_plan=[],
    )

    assert hits == []


def test_rule_hit_builder_reports_masking_plan_hits() -> None:
    hits = GuardrailRuleHitBuilder().allow_rule_hits(
        original_sql="SELECT customers.user_email FROM customers LIMIT 25",
        rewritten_sql="SELECT customers.user_email FROM customers LIMIT 25",
        masking_plan=[
            MaskingInstruction(
                field_name="customers.user_email",
                strategy=MaskingStrategy.PARTIAL,
                reason="P1 field requires masking before results leave governance.",
            )
        ],
    )

    assert [hit.rule_code for hit in hits] == [GuardrailRuleCode.MASKING_REQUIRED]
    assert hits[0].object_name == "customers.user_email"


def test_rule_hit_builder_reports_unauthorized_object_denial() -> None:
    hits = GuardrailRuleHitBuilder().deny_rule_hits(
        sql_text="SELECT orders.user_id FROM orders",
        error_code=ErrorCode.SQL_DENY_OBJECT,
    )

    assert [hit.rule_code for hit in hits] == [GuardrailRuleCode.UNAUTHORIZED_OBJECT]


def test_rule_hit_builder_reports_multiple_statement_denial() -> None:
    hits = GuardrailRuleHitBuilder().deny_rule_hits(
        sql_text="SELECT * FROM orders; DROP TABLE orders",
        error_code=ErrorCode.SQL_DENY_STATEMENT,
    )

    assert [hit.rule_code for hit in hits] == [GuardrailRuleCode.MULTIPLE_STATEMENTS]


def test_rule_hit_builder_reports_write_operation_denial() -> None:
    hits = GuardrailRuleHitBuilder().deny_rule_hits(
        sql_text="DROP TABLE orders",
        error_code=ErrorCode.SQL_DENY_STATEMENT,
    )

    assert [hit.rule_code for hit in hits] == [GuardrailRuleCode.WRITE_OPERATION]
