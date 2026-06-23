"""Canonical metric evaluation for MVP seed data checks."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog


TableRows = Mapping[str, tuple[Mapping[str, Any], ...]]


class MetricEvaluator:
    """Evaluate canonical metrics against row-like seed data."""

    def __init__(self, data_model_catalog: DataModelCatalog | None = None) -> None:
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()

    def evaluate(self, metric_name: str, rows_by_table: TableRows) -> Decimal | int:
        metric = self._data_model_catalog.get_metric(metric_name)
        if metric is None:
            raise ValueError(f"Unknown metric {metric_name}.")

        if metric.name == "revenue":
            return self._evaluate_revenue(rows_by_table)
        if metric.name == "order_count":
            return self._evaluate_order_count(rows_by_table)
        if metric.name == "refund_rate":
            return self._evaluate_refund_rate(rows_by_table)
        if metric.name == "active_users":
            return self._evaluate_active_users(rows_by_table)

        raise ValueError(f"Metric {metric_name} has no evaluator.")

    def canonical_sql_definition(self, metric_name: str) -> str:
        metric = self._data_model_catalog.get_metric(metric_name)
        if metric is None:
            raise ValueError(f"Unknown metric {metric_name}.")
        return metric.sql_definition

    def _evaluate_revenue(self, rows_by_table: TableRows) -> Decimal:
        revenue = Decimal("0")
        for order in rows_by_table.get("orders", ()):
            if order.get("status") == "paid":
                revenue += self._decimal_value(order.get("order_amount"))
        return revenue

    def _evaluate_order_count(self, rows_by_table: TableRows) -> int:
        order_ids = {
            order.get("order_id")
            for order in rows_by_table.get("orders", ())
            if order.get("order_id") is not None
        }
        return len(order_ids)

    def _evaluate_refund_rate(self, rows_by_table: TableRows) -> Decimal:
        refund_amount = Decimal("0")
        for refund in rows_by_table.get("refunds", ()):
            refund_amount += self._decimal_value(refund.get("refund_amount"))

        order_amount = Decimal("0")
        for order in rows_by_table.get("orders", ()):
            order_amount += self._decimal_value(order.get("order_amount"))

        if order_amount == Decimal("0"):
            return Decimal("0")
        return refund_amount / order_amount

    def _evaluate_active_users(self, rows_by_table: TableRows) -> int:
        customer_ids = {
            event.get("customer_id")
            for event in rows_by_table.get("web_events", ())
            if event.get("customer_id") is not None
        }
        return len(customer_ids)

    def _decimal_value(self, value: Any) -> Decimal:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))
