"""Minimal SQL guardrail for the Overall Architecture workflow.

This file implements the first small, testable slice of FR-01-004:
SQL must pass through a guardrail before database execution.
"""

from __future__ import annotations

import re

from chatbi.core.contracts import (
    ErrorCode,
    GuardrailDecision,
    GuardrailResult,
    QueryRequest,
    TableResult,
    UserRole,
)
from chatbi.data_model import DataModelCatalog, build_default_data_model_catalog
from chatbi.governance.audit import GuardrailAuditLog, GuardrailAuditRecord
from chatbi.governance.masking import PiiResultMasker


_DANGEROUS_STATEMENT_PATTERN = re.compile(
    r"\b(drop|delete|update|insert|alter|truncate)\b",
    re.IGNORECASE,
)
_COMMENT_ESCAPE_PATTERN = re.compile(r"(--|/\*|\*/|#)")
_RISKY_UNION_PATTERN = re.compile(r"\bunion\b", re.IGNORECASE)
_TAUTOLOGY_PATTERN = re.compile(
    r"\b(or|and)\b\s+(['\"]?\w+['\"]?\s*=\s*['\"]?\w+['\"]?)",
    re.IGNORECASE,
)
_RISKY_FUNCTION_PATTERN = re.compile(
    r"\b(sleep|benchmark|load_file|xp_cmdshell)\s*\(",
    re.IGNORECASE,
)
_TABLE_REFERENCE_PATTERN = re.compile(
    r"\b(from|join)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)"
    r"(?:\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?",
    re.IGNORECASE,
)
_QUALIFIED_COLUMN_PATTERN = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b"
)
_LIMIT_PATTERN = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)
_DEFAULT_ROW_LIMIT = 100
_DEFAULT_TIMEOUT_MS = 30_000

_ALLOWED_TABLES_BY_ROLE: dict[UserRole, frozenset[str] | None] = {
    UserRole.BUSINESS_USER: frozenset({"orders", "revenue_by_month"}),
    UserRole.ANALYST: frozenset({"orders", "revenue_by_month", "users"}),
    UserRole.ADMIN: None,
}
_RESTRICTED_COLUMNS_BY_ROLE: dict[UserRole, frozenset[str]] = {
    UserRole.BUSINESS_USER: frozenset({"orders.user_id"}),
    UserRole.ANALYST: frozenset(),
    UserRole.ADMIN: frozenset(),
}


class SimpleSqlGuardrail:
    """Allow simple SELECT statements and deny dangerous SQL statements."""

    def __init__(
        self,
        default_row_limit: int = _DEFAULT_ROW_LIMIT,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        audit_log: GuardrailAuditLog | None = None,
        result_masker: PiiResultMasker | None = None,
        data_model_catalog: DataModelCatalog | None = None,
    ) -> None:
        self._default_row_limit = default_row_limit
        self._timeout_ms = timeout_ms
        self._audit_log = audit_log
        self._data_model_catalog = data_model_catalog or build_default_data_model_catalog()
        self._result_masker = result_masker or PiiResultMasker(
            data_model_catalog=self._data_model_catalog,
        )

    def check(self, sql_text: str, request: QueryRequest, trace_id: str) -> GuardrailResult:
        normalized_sql = self._normalize(sql_text)

        if not normalized_sql:
            result = self._deny(trace_id, "SQL text is empty.")
            return self._record_decision(sql_text, request, result)

        if self._contains_multiple_statements(normalized_sql):
            result = self._deny(trace_id, "Only a single SELECT statement is allowed.")
            return self._record_decision(sql_text, request, result)

        if self._has_structural_risk(normalized_sql):
            result = self._deny(trace_id, "SQL contains a blocked injection pattern.")
            return self._record_decision(sql_text, request, result)

        if _DANGEROUS_STATEMENT_PATTERN.search(normalized_sql):
            result = self._deny(trace_id, "Only SELECT statements are allowed.")
            return self._record_decision(sql_text, request, result)

        if not normalized_sql.lower().startswith("select "):
            result = self._deny(trace_id, "Only SELECT statements are allowed.")
            return self._record_decision(sql_text, request, result)

        object_denial = self._check_object_access(normalized_sql, request.role, trace_id)
        if object_denial is not None:
            return self._record_decision(sql_text, request, object_denial)

        safe_sql = self._ensure_limit(normalized_sql)
        result = GuardrailResult(
            decision=GuardrailDecision.ALLOW,
            trace_id=trace_id,
            safe_sql=safe_sql,
        )
        return self._record_decision(sql_text, request, result)

    def mask_result(self, table_result: TableResult) -> TableResult:
        return self._result_masker.mask(table_result)

    def check_timeout(
        self,
        elapsed_ms: int,
        sql_text: str,
        request: QueryRequest,
        trace_id: str,
    ) -> GuardrailResult | None:
        if elapsed_ms <= self._timeout_ms:
            return None

        message = (
            f"Query exceeded timeout of {self._timeout_ms}ms "
            f"after running for {elapsed_ms}ms."
        )
        result = GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id=trace_id,
            error_code=ErrorCode.SQL_DENY_TIMEOUT,
            message=message,
        )
        return self._record_decision(sql_text, request, result)

    def _deny(self, trace_id: str, message: str) -> GuardrailResult:
        return GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id=trace_id,
            error_code=ErrorCode.SQL_DENY_STATEMENT,
            message=message,
        )

    def _deny_object(self, trace_id: str, message: str) -> GuardrailResult:
        return GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id=trace_id,
            error_code=ErrorCode.SQL_DENY_OBJECT,
            message=message,
        )

    def _record_decision(
        self,
        original_sql: str,
        request: QueryRequest,
        result: GuardrailResult,
    ) -> GuardrailResult:
        if self._audit_log is None:
            return result

        record = GuardrailAuditRecord(
            trace_id=result.trace_id,
            user_id=request.user_id,
            role=request.role,
            original_sql=original_sql,
            decision=result.decision,
            safe_sql=result.safe_sql,
            error_code=result.error_code,
            message=result.message,
        )
        self._audit_log.save(record)
        return result

    def _normalize(self, sql_text: str) -> str:
        return " ".join(sql_text.strip().split())

    def _contains_multiple_statements(self, sql_text: str) -> bool:
        stripped_sql = sql_text.rstrip(";")
        return ";" in stripped_sql

    def _has_structural_risk(self, sql_text: str) -> bool:
        if _COMMENT_ESCAPE_PATTERN.search(sql_text):
            return True

        if _RISKY_UNION_PATTERN.search(sql_text):
            return True

        if _RISKY_FUNCTION_PATTERN.search(sql_text):
            return True

        for match in _TAUTOLOGY_PATTERN.finditer(sql_text):
            expression = match.group(2)
            if self._is_tautology(expression):
                return True

        return False

    def _is_tautology(self, expression: str) -> bool:
        left_value, right_value = expression.split("=", maxsplit=1)
        normalized_left_value = self._normalize_literal(left_value)
        normalized_right_value = self._normalize_literal(right_value)
        return normalized_left_value == normalized_right_value

    def _normalize_literal(self, value: str) -> str:
        stripped_value = value.strip()
        stripped_value = stripped_value.strip("'")
        stripped_value = stripped_value.strip('"')
        return stripped_value.lower()

    def _ensure_limit(self, sql_text: str) -> str:
        if _LIMIT_PATTERN.search(sql_text):
            return sql_text

        sql_without_trailing_semicolon = sql_text.rstrip(";")
        return f"{sql_without_trailing_semicolon} LIMIT {self._default_row_limit}"

    def _check_object_access(
        self,
        sql_text: str,
        role: UserRole,
        trace_id: str,
    ) -> GuardrailResult | None:
        table_aliases = self._extract_table_aliases(sql_text)
        allowed_tables = self._allowed_tables_for_role(role)
        for table_name in table_aliases.values():
            if allowed_tables is not None and table_name not in allowed_tables:
                return self._deny_object(
                    trace_id,
                    f"Role {role.value} is not allowed to query table {table_name}.",
                )

        referenced_columns = self._extract_referenced_columns(sql_text, table_aliases)
        p0_denial = self._check_p0_column_access(referenced_columns, role, trace_id)
        if p0_denial is not None:
            return p0_denial

        restricted_columns = _RESTRICTED_COLUMNS_BY_ROLE[role]
        for column_name in referenced_columns:
            if column_name in restricted_columns:
                return self._deny_object(
                    trace_id,
                    f"Role {role.value} is not allowed to query column {column_name}.",
                )
        return None

    def _allowed_tables_for_role(self, role: UserRole) -> frozenset[str] | None:
        configured_tables = _ALLOWED_TABLES_BY_ROLE[role]
        if role is not UserRole.ANALYST or configured_tables is None:
            return configured_tables

        return frozenset(
            (
                *configured_tables,
                *self._data_model_catalog.business_table_names(),
            )
        )

    def _check_p0_column_access(
        self,
        referenced_columns: frozenset[str],
        role: UserRole,
        trace_id: str,
    ) -> GuardrailResult | None:
        p0_fields = frozenset(self._data_model_catalog.p0_fields())
        for column_name in referenced_columns:
            if column_name in p0_fields:
                return self._deny_object(
                    trace_id,
                    f"Role {role.value} is not allowed to query P0 field {column_name}.",
                )
        return None

    def _extract_table_aliases(self, sql_text: str) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for match in _TABLE_REFERENCE_PATTERN.finditer(sql_text):
            table_name = self._normalize_identifier(match.group(2))
            alias = match.group(3)
            aliases[table_name] = table_name
            if alias is not None:
                aliases[self._normalize_identifier(alias)] = table_name
        return aliases

    def _extract_referenced_columns(
        self,
        sql_text: str,
        table_aliases: dict[str, str],
    ) -> frozenset[str]:
        referenced_columns: set[str] = set()
        for qualifier, column in _QUALIFIED_COLUMN_PATTERN.findall(sql_text):
            normalized_qualifier = self._normalize_identifier(qualifier)
            table_name = table_aliases.get(normalized_qualifier, normalized_qualifier)
            normalized_column = self._normalize_identifier(column)
            referenced_columns.add(f"{table_name}.{normalized_column}")

        unique_table_names = set(table_aliases.values())
        if len(unique_table_names) == 1:
            table_name = unique_table_names.pop()
            for column in self._extract_selected_columns(sql_text):
                if "." not in column:
                    normalized_column = self._normalize_identifier(column)
                    referenced_columns.add(f"{table_name}.{normalized_column}")
        return frozenset(referenced_columns)

    def _extract_selected_columns(self, sql_text: str) -> tuple[str, ...]:
        lowered_sql = sql_text.lower()
        from_index = lowered_sql.find(" from ")
        if from_index == -1:
            return ()

        select_clause = sql_text[len("select "):from_index]
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

    def _normalize_identifier(self, identifier: str) -> str:
        return identifier.split(".")[-1].strip().lower()
