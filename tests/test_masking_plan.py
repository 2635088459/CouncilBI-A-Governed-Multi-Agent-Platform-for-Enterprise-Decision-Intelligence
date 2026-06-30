from chatbi.governance import MaskingPlanGenerator


def test_masking_plan_generator_returns_empty_plan_for_non_p1_fields() -> None:
    plan = MaskingPlanGenerator().generate(
        "SELECT order_amount FROM orders LIMIT 25"
    )

    assert plan == []


def test_masking_plan_generator_marks_qualified_p1_field() -> None:
    plan = MaskingPlanGenerator().generate(
        "SELECT customers.user_email FROM customers LIMIT 25"
    )

    assert len(plan) == 1
    assert plan[0].field_name == "customers.user_email"
    assert plan[0].strategy.value == "partial"
    assert plan[0].reason == "P1 field requires masking before results leave governance."


def test_masking_plan_generator_resolves_aliases_for_p1_fields() -> None:
    plan = MaskingPlanGenerator().generate(
        "SELECT c.user_email FROM customers AS c LIMIT 25"
    )

    assert len(plan) == 1
    assert plan[0].field_name == "customers.user_email"


def test_masking_plan_generator_returns_stable_plan_for_multiple_p1_fields() -> None:
    plan = MaskingPlanGenerator().generate(
        "SELECT phone, user_email FROM customers LIMIT 25"
    )

    assert [instruction.field_name for instruction in plan] == [
        "customers.phone",
        "customers.user_email",
    ]
