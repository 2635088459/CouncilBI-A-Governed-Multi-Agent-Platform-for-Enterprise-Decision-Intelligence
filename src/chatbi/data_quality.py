"""Executable data quality checks backed by the data model catalog."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from chatbi.data_model import (
    DataModelCatalog,
    QualityRuleDefinition,
    QualityRuleType,
    build_default_data_model_catalog,
)


@dataclass(frozen=True, slots=True)
class DataQualityViolation:
    table_name: str
    rule_type: QualityRuleType
    row_index: int
    column_name: str | None
    message: str


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    table_name: str
    checked_rows: int
    violations: tuple[DataQualityViolation, ...]

    @property
    def passed(self) -> bool:
        return not self.violations


class DataQualityValidator:
    """Validate row-like data against table quality rules."""

    def __init__(self, data_model_catalog: DataModelCatalog | None = None) -> None:
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()

    def validate_rows(
        self,
        table_name: str,
        rows: tuple[Mapping[str, Any], ...],
    ) -> DataQualityReport:
        table = self._data_model_catalog.get_table(table_name)
        if table is None:
            return DataQualityReport(
                table_name=table_name,
                checked_rows=len(rows),
                violations=(
                    DataQualityViolation(
                        table_name=table_name,
                        rule_type=QualityRuleType.NON_NULL,
                        row_index=-1,
                        column_name=None,
                        message=f"Unknown table {table_name}.",
                    ),
                ),
            )

        violations: list[DataQualityViolation] = []
        for row_index, row in enumerate(rows):
            for rule in table.quality_rules:
                violation = self._validate_rule(table_name, row_index, row, rule)
                if violation is not None:
                    violations.append(violation)

        return DataQualityReport(
            table_name=table_name,
            checked_rows=len(rows),
            violations=tuple(violations),
        )

    def _validate_rule(
        self,
        table_name: str,
        row_index: int,
        row: Mapping[str, Any],
        rule: QualityRuleDefinition,
    ) -> DataQualityViolation | None:
        if rule.rule_type is QualityRuleType.NON_NULL:
            return self._validate_non_null(table_name, row_index, row, rule)
        if rule.rule_type is QualityRuleType.NON_NEGATIVE:
            return self._validate_non_negative(table_name, row_index, row, rule)
        if rule.rule_type is QualityRuleType.PARTITION_REQUIRED:
            return self._validate_partition_value(table_name, row_index, row, rule)
        return None

    def _validate_non_null(
        self,
        table_name: str,
        row_index: int,
        row: Mapping[str, Any],
        rule: QualityRuleDefinition,
    ) -> DataQualityViolation | None:
        column_name = rule.column_name
        if column_name is None:
            return None

        value = row.get(column_name)
        if value is not None and value != "":
            return None

        return DataQualityViolation(
            table_name=table_name,
            rule_type=rule.rule_type,
            row_index=row_index,
            column_name=column_name,
            message=f"{table_name}.{column_name} must not be null.",
        )

    def _validate_non_negative(
        self,
        table_name: str,
        row_index: int,
        row: Mapping[str, Any],
        rule: QualityRuleDefinition,
    ) -> DataQualityViolation | None:
        column_name = rule.column_name
        if column_name is None:
            return None

        value = row.get(column_name)
        if value is None:
            return None

        if isinstance(value, int | float | Decimal) and value >= 0:
            return None

        return DataQualityViolation(
            table_name=table_name,
            rule_type=rule.rule_type,
            row_index=row_index,
            column_name=column_name,
            message=f"{table_name}.{column_name} must be non-negative.",
        )

    def _validate_partition_value(
        self,
        table_name: str,
        row_index: int,
        row: Mapping[str, Any],
        rule: QualityRuleDefinition,
    ) -> DataQualityViolation | None:
        column_name = rule.column_name
        if column_name is None:
            return None

        value = row.get(column_name)
        if value is not None and value != "":
            return None

        return DataQualityViolation(
            table_name=table_name,
            rule_type=rule.rule_type,
            row_index=row_index,
            column_name=column_name,
            message=f"{table_name}.{column_name} is required for partition pruning.",
        )
