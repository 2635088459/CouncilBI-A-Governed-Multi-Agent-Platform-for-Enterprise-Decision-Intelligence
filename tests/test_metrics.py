from decimal import Decimal

import pytest

from chatbi.metrics import MetricEvaluator


def test_metric_evaluator_returns_canonical_revenue_sql_definition() -> None:
    evaluator = MetricEvaluator()

    sql_definition = evaluator.canonical_sql_definition("revenue")

    assert sql_definition == "SUM(orders.order_amount) WHERE status='paid'"


def test_metric_evaluator_calculates_revenue_from_seed_orders() -> None:
    evaluator = MetricEvaluator()

    revenue = evaluator.evaluate(
        "revenue",
        {
            "orders": (
                {"order_id": 1, "order_amount": "100.50", "status": "paid"},
                {"order_id": 2, "order_amount": "25.00", "status": "cancelled"},
                {"order_id": 3, "order_amount": "40.25", "status": "paid"},
            ),
        },
    )

    assert revenue == Decimal("140.75")


def test_metric_evaluator_calculates_order_count_from_distinct_order_ids() -> None:
    evaluator = MetricEvaluator()

    order_count = evaluator.evaluate(
        "order_count",
        {
            "orders": (
                {"order_id": 1},
                {"order_id": 1},
                {"order_id": 2},
            ),
        },
    )

    assert order_count == 2


def test_metric_evaluator_calculates_refund_rate() -> None:
    evaluator = MetricEvaluator()

    refund_rate = evaluator.evaluate(
        "refund_rate",
        {
            "orders": (
                {"order_id": 1, "order_amount": "80"},
                {"order_id": 2, "order_amount": "20"},
            ),
            "refunds": (
                {"refund_id": 1, "refund_amount": "10"},
                {"refund_id": 2, "refund_amount": "5"},
            ),
        },
    )

    assert refund_rate == Decimal("0.15")


def test_metric_evaluator_calculates_active_users_from_web_events() -> None:
    evaluator = MetricEvaluator()

    active_users = evaluator.evaluate(
        "active_users",
        {
            "web_events": (
                {"event_id": "evt_1", "customer_id": 1},
                {"event_id": "evt_2", "customer_id": 1},
                {"event_id": "evt_3", "customer_id": 2},
            ),
        },
    )

    assert active_users == 2


def test_metric_evaluator_rejects_unknown_metric() -> None:
    evaluator = MetricEvaluator()

    with pytest.raises(ValueError, match="Unknown metric gross_margin"):
        evaluator.evaluate("gross_margin", {})
