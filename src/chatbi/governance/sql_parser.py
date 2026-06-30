"""Small SQL reference parser for guardrail decisions.

This parser is intentionally conservative. It does not execute SQL and does
not try to understand every SQL dialect feature. Its job is to extract the
table and field references needed by the policy layer.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_TABLE_REFERENCE_PATTERN = re.compile(
    r"\b(from|join)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)"
    r"(?:\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?",
    re.IGNORECASE,
)
_QUALIFIED_COLUMN_PATTERN = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b"
)


@dataclass(frozen=True, slots=True)
class SqlReferenceSet:
    """Tables, aliases, and fields referenced by a SQL string."""

    table_aliases: dict[str, str]
    table_names: frozenset[str]
    field_names: frozenset[str]


class SqlReferenceParser:
    """Extract simple table and field references from SELECT SQL."""

    def parse(self, sql_text: str) -> SqlReferenceSet:
        normalized_sql = self._normalize(sql_text)
        table_aliases = self._extract_table_aliases(normalized_sql)
        field_names = self._extract_referenced_fields(normalized_sql, table_aliases)
        return SqlReferenceSet(
            table_aliases=table_aliases,
            table_names=frozenset(table_aliases.values()),
            field_names=field_names,
        )

    def _extract_table_aliases(self, sql_text: str) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for match in _TABLE_REFERENCE_PATTERN.finditer(sql_text):
            table_name = self._normalize_identifier(match.group(2))
            alias = match.group(3)
            aliases[table_name] = table_name
            if alias is not None:
                aliases[self._normalize_identifier(alias)] = table_name
        return aliases

    def _extract_referenced_fields(
        self,
        sql_text: str,
        table_aliases: dict[str, str],
    ) -> frozenset[str]:
        referenced_fields: set[str] = set()
        for qualifier, column in _QUALIFIED_COLUMN_PATTERN.findall(sql_text):
            normalized_qualifier = self._normalize_identifier(qualifier)
            table_name = table_aliases.get(normalized_qualifier, normalized_qualifier)
            normalized_column = self._normalize_identifier(column)
            referenced_fields.add(f"{table_name}.{normalized_column}")

        unique_table_names = set(table_aliases.values())
        if len(unique_table_names) == 1:
            table_name = unique_table_names.pop()
            for column in self._extract_selected_columns(sql_text):
                if "." not in column:
                    normalized_column = self._normalize_identifier(column)
                    referenced_fields.add(f"{table_name}.{normalized_column}")
        return frozenset(referenced_fields)

    def _extract_selected_columns(self, sql_text: str) -> tuple[str, ...]:
        lowered_sql = sql_text.lower()
        from_index = lowered_sql.find(" from ")
        if from_index == -1:
            return ()

        select_clause = sql_text[len("select ") : from_index]
        selected_columns: list[str] = []
        for raw_column in select_clause.split(","):
            column = raw_column.strip()
            if not column:
                continue
            if "(" in column:
                continue

            column_without_alias = column.split(" ", maxsplit=1)[0]
            selected_columns.append(column_without_alias)

        return tuple(selected_columns)

    def _normalize(self, sql_text: str) -> str:
        return " ".join(sql_text.strip().split())

    def _normalize_identifier(self, identifier: str) -> str:
        return identifier.split(".")[-1].strip().lower()
