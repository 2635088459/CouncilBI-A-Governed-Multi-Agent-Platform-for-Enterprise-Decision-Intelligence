from chatbi.core.contracts import TableResult
from chatbi.data_model import (
    ColumnDefinition,
    DataDomain,
    DataModelCatalog,
    SensitivityClass,
    TableDefinition,
)
from chatbi.governance.masking import PiiResultMasker
from chatbi.governance.simple_guardrail import SimpleSqlGuardrail


def test_pii_result_masker_masks_known_pii_columns() -> None:
    table_result = TableResult(
        columns=("user_email", "phone", "customer_name", "revenue"),
        rows=(
            {
                "user_email": "alice@example.com",
                "phone": "408-555-1234",
                "customer_name": "Alice Chen",
                "revenue": 1000,
            },
        ),
    )

    masked_result = PiiResultMasker().mask(table_result)
    masked_row = masked_result.rows[0]

    assert masked_result.columns == table_result.columns
    assert masked_row["user_email"] == "a***@example.com"
    assert masked_row["phone"] == "***-***-1234"
    assert masked_row["customer_name"] == "A."
    assert masked_row["revenue"] == 1000


def test_pii_result_masker_leaves_non_pii_columns_unchanged() -> None:
    table_result = TableResult(
        columns=("month", "revenue"),
        rows=({"month": "2026-01", "revenue": 1000},),
    )

    masked_result = PiiResultMasker().mask(table_result)

    assert masked_result == table_result


def test_pii_result_masker_masks_qualified_p1_columns_from_data_model() -> None:
    table_result = TableResult(
        columns=("customers.user_email", "orders.order_amount"),
        rows=(
            {
                "customers.user_email": "alice@example.com",
                "orders.order_amount": 1000,
            },
        ),
    )

    masked_result = PiiResultMasker().mask(table_result)
    masked_row = masked_result.rows[0]

    assert masked_row["customers.user_email"] == "a***@example.com"
    assert masked_row["orders.order_amount"] == 1000


def test_pii_result_masker_uses_custom_data_model_p1_field() -> None:
    catalog = DataModelCatalog(
        tables=(
            TableDefinition(
                name="customers",
                domain=DataDomain.BUSINESS_ANALYTICS,
                columns=(
                    ColumnDefinition("customer_id", "bigint", is_primary_key=True),
                    ColumnDefinition("loyalty_code", "string", sensitivity=SensitivityClass.P1),
                ),
            ),
        ),
    )
    table_result = TableResult(
        columns=("loyalty_code", "revenue"),
        rows=({"loyalty_code": "VIP-12345", "revenue": 1000},),
    )

    masked_result = PiiResultMasker(data_model_catalog=catalog).mask(table_result)
    masked_row = masked_result.rows[0]

    assert masked_row["loyalty_code"] == "[masked]"
    assert masked_row["revenue"] == 1000


def test_guardrail_masks_pii_fields_before_returning_results() -> None:
    table_result = TableResult(
        columns=("user_email", "phone"),
        rows=(
            {
                "user_email": "bob@example.com",
                "phone": "5551234567",
            },
        ),
    )

    masked_result = SimpleSqlGuardrail().mask_result(table_result)
    masked_row = masked_result.rows[0]

    assert masked_row["user_email"] == "b***@example.com"
    assert masked_row["phone"] == "***-***-4567"
