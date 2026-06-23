"""PII masking for query results returned by governed SQL."""

from __future__ import annotations

from typing import Any, Mapping

from chatbi.core.contracts import TableResult
from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog


class PiiResultMasker:
    """Mask PII fields in a table result before it leaves governance."""

    def __init__(self, data_model_catalog: DataModelCatalog | None = None) -> None:
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()

    def mask(self, table_result: TableResult) -> TableResult:
        masked_rows: list[Mapping[str, Any]] = []

        for row in table_result.rows:
            masked_row = self._mask_row(row)
            masked_rows.append(masked_row)

        return TableResult(
            columns=table_result.columns,
            rows=tuple(masked_rows),
        )

    def _mask_row(self, row: Mapping[str, Any]) -> Mapping[str, Any]:
        masked_row: dict[str, Any] = {}

        for column_name, value in row.items():
            normalized_column_name = self._normalize_column_name(column_name)
            if self._should_mask(normalized_column_name):
                masked_row[column_name] = self._mask_value(normalized_column_name, value)
            else:
                masked_row[column_name] = value

        return masked_row

    def _should_mask(self, normalized_column_name: str) -> bool:
        p1_fields = frozenset(self._data_model_catalog.p1_fields())
        if normalized_column_name in p1_fields:
            return True

        p1_column_names = {
            self._normalize_column_name(field_name.split(".")[-1])
            for field_name in p1_fields
        }
        return normalized_column_name in p1_column_names

    def _mask_value(self, column_name: str, value: Any) -> Any:
        if value is None:
            return None

        text_value = str(value)
        simple_column_name = column_name.split(".")[-1]
        if simple_column_name == "user_email":
            return self._mask_email(text_value)
        if simple_column_name == "phone":
            return self._mask_phone(text_value)
        if simple_column_name == "customer_name":
            return self._mask_customer_name(text_value)
        return "[masked]"

    def _mask_email(self, email: str) -> str:
        if "@" not in email:
            return "[masked-email]"

        local_part, domain = email.split("@", maxsplit=1)
        if not local_part:
            return f"***@{domain}"

        first_character = local_part[0]
        return f"{first_character}***@{domain}"

    def _mask_phone(self, phone: str) -> str:
        digits = ""
        for character in phone:
            if character.isdigit():
                digits += character

        if len(digits) < 4:
            return "***"

        last_four_digits = digits[-4:]
        return f"***-***-{last_four_digits}"

    def _mask_customer_name(self, customer_name: str) -> str:
        stripped_name = customer_name.strip()
        if not stripped_name:
            return "[masked-name]"

        first_character = stripped_name[0]
        return f"{first_character}."

    def _normalize_column_name(self, column_name: str) -> str:
        return column_name.strip().lower()
