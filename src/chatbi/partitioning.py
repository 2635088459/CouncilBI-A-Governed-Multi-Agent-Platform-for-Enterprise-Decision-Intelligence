"""Partition pruning checks for generated SQL."""

from __future__ import annotations

import re
from dataclasses import dataclass

from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog


_TABLE_REFERENCE_PATTERN = re.compile(
    r"\b(from|join)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PartitionPruningReport:
    table_name: str
    partition_column: str | None
    uses_lower_bound: bool
    uses_upper_bound: bool

    @property
    def passed(self) -> bool:
        return self.partition_column is None or (
            self.uses_lower_bound and self.uses_upper_bound
        )


class PartitionPruningChecker:
    """Check that partitioned tables are filtered by their partition column."""

    def __init__(self, data_model_catalog: DataModelCatalog | None = None) -> None:
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()

    def check(self, sql_text: str) -> tuple[PartitionPruningReport, ...]:
        reports: list[PartitionPruningReport] = []
        for table_name in self._referenced_table_names(sql_text):
            table = self._data_model_catalog.get_table(table_name)
            if table is None or table.partition_column is None:
                continue

            qualified_column = f"{table.name}.{table.partition_column}"
            reports.append(
                PartitionPruningReport(
                    table_name=table.name,
                    partition_column=table.partition_column,
                    uses_lower_bound=self._has_bound(sql_text, qualified_column, (">=", ">")),
                    uses_upper_bound=self._has_bound(sql_text, qualified_column, ("<=", "<")),
                )
            )
        return tuple(reports)

    def passes(self, sql_text: str) -> bool:
        return all(report.passed for report in self.check(sql_text))

    def _referenced_table_names(self, sql_text: str) -> tuple[str, ...]:
        names: list[str] = []
        for match in _TABLE_REFERENCE_PATTERN.finditer(sql_text):
            table_name = match.group(2).split(".")[-1].lower()
            if table_name not in names:
                names.append(table_name)
        return tuple(names)

    def _has_bound(
        self,
        sql_text: str,
        qualified_column: str,
        operators: tuple[str, ...],
    ) -> bool:
        for operator in operators:
            pattern = (
                rf"\b{re.escape(qualified_column)}\b\s*"
                rf"{re.escape(operator)}\s*"
                r"(date\s+)?['\"]?\d{4}-\d{2}-\d{2}"
            )
            if re.search(pattern, sql_text, re.IGNORECASE):
                return True
        return False
