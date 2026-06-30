from chatbi.core.contracts import UserRole
from chatbi.governance import SqlObjectAccessPolicy


def test_object_access_policy_allows_business_user_default_table() -> None:
    policy = SqlObjectAccessPolicy()

    violation = policy.check(
        role=UserRole.BUSINESS_USER,
        table_names=frozenset({"orders"}),
        field_names=frozenset({"orders.order_amount"}),
    )

    assert violation is None


def test_object_access_policy_denies_business_user_restricted_table() -> None:
    policy = SqlObjectAccessPolicy()

    violation = policy.check(
        role=UserRole.BUSINESS_USER,
        table_names=frozenset({"users"}),
        field_names=frozenset(),
    )

    assert violation is not None
    assert violation.object_name == "users"
    assert violation.message == "Role business_user is not allowed to query table users."


def test_object_access_policy_denies_p0_field_from_catalog() -> None:
    policy = SqlObjectAccessPolicy()

    violation = policy.check(
        role=UserRole.ANALYST,
        table_names=frozenset({"customers"}),
        field_names=frozenset({"customers.customer_id"}),
    )

    assert violation is not None
    assert violation.object_name == "customers.customer_id"
    assert violation.message == (
        "Role analyst is not allowed to query P0 field customers.customer_id."
    )


def test_object_access_policy_reports_p1_fields_that_need_masking() -> None:
    policy = SqlObjectAccessPolicy()

    masking_fields = policy.masking_fields_for(
        frozenset({"customers.user_email", "orders.order_amount"})
    )

    assert masking_fields == ("customers.user_email",)
