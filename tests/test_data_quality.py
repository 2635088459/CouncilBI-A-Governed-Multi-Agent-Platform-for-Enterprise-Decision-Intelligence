from chatbi.data_model import QualityRuleType
from chatbi.data_quality import DataQualityValidator


def test_data_quality_validator_passes_valid_order_rows() -> None:
    report = DataQualityValidator().validate_rows(
        "orders",
        (
            {
                "order_id": 1001,
                "customer_id": 501,
                "product_id": 301,
                "region_id": "us-west",
                "order_amount": 125.5,
                "status": "paid",
                "order_date": "2026-06-01",
            },
        ),
    )

    assert report.passed
    assert report.checked_rows == 1
    assert report.violations == ()


def test_data_quality_validator_rejects_null_primary_key() -> None:
    report = DataQualityValidator().validate_rows(
        "orders",
        (
            {
                "order_id": None,
                "customer_id": 501,
                "product_id": 301,
                "region_id": "us-west",
                "order_amount": 125.5,
                "status": "paid",
                "order_date": "2026-06-01",
            },
        ),
    )

    assert not report.passed
    assert report.violations[0].rule_type is QualityRuleType.NON_NULL
    assert report.violations[0].column_name == "order_id"


def test_data_quality_validator_rejects_negative_amount() -> None:
    report = DataQualityValidator().validate_rows(
        "orders",
        (
            {
                "order_id": 1001,
                "customer_id": 501,
                "product_id": 301,
                "region_id": "us-west",
                "order_amount": -10,
                "status": "paid",
                "order_date": "2026-06-01",
            },
        ),
    )

    assert not report.passed
    assert report.violations[0].rule_type is QualityRuleType.NON_NEGATIVE
    assert report.violations[0].column_name == "order_amount"


def test_data_quality_validator_requires_partition_column_for_large_fact_table() -> None:
    report = DataQualityValidator().validate_rows(
        "orders",
        (
            {
                "order_id": 1001,
                "customer_id": 501,
                "product_id": 301,
                "region_id": "us-west",
                "order_amount": 125.5,
                "status": "paid",
            },
        ),
    )

    assert not report.passed
    assert report.violations[0].rule_type is QualityRuleType.PARTITION_REQUIRED
    assert report.violations[0].column_name == "order_date"


def test_data_quality_validator_reports_unknown_table() -> None:
    report = DataQualityValidator().validate_rows(
        "missing_table",
        ({"id": 1},),
    )

    assert not report.passed
    assert report.checked_rows == 1
    assert report.violations[0].message == "Unknown table missing_table."
