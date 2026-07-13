"""SQL statement validation for the guardrail layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


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
# A `WITH ... AS (...) SELECT ...` common table expression is a single
# read-only statement, not a write, and is common enough in real analytical
# SQL (period-over-period comparisons, running totals) that rejecting it
# outright pushed the LLM-generation fallback in simple_orchestrator.py
# toward reformulating perfectly valid CTEs as flatter queries or, worse,
# non-SQL prose. Still denied regardless of prefix: any statement matching
# _DANGEROUS_STATEMENT_PATTERN or _has_structural_risk below.
_ALLOWED_STATEMENT_PREFIXES = ("select ", "with ")


class SqlValidationViolationCode(StrEnum):
    EMPTY_SQL = "empty_sql"
    MULTIPLE_STATEMENTS = "multiple_statements"
    STRUCTURAL_RISK = "structural_risk"
    NON_SELECT_STATEMENT = "non_select_statement"
    # 10-followups/13: distinct from NON_SELECT_STATEMENT — no dangerous
    # DML/DDL keyword was found at all, so this is not a write attempt. The
    # model's output simply wasn't recognizable as a single read-only query
    # (e.g. prose, a refusal, an explanation) — most often because the
    # question asked about a metric/table the schema doesn't have.
    UNRECOGNIZED_QUERY_OUTPUT = "unrecognized_query_output"


@dataclass(frozen=True, slots=True)
class SqlValidationResult:
    """Outcome from validating SQL text before database execution."""

    normalized_sql: str
    violation_code: SqlValidationViolationCode | None = None
    message: str | None = None

    @property
    def passed(self) -> bool:
        return self.violation_code is None


class SqlStatementValidator:
    """Deny unsafe or non-SELECT SQL before any execution path can use it."""

    def validate(self, sql_text: str) -> SqlValidationResult:
        normalized_sql = self._normalize(sql_text)

        if not normalized_sql:
            return self._deny(
                normalized_sql,
                SqlValidationViolationCode.EMPTY_SQL,
                "SQL text is empty.",
            )

        if self._contains_multiple_statements(normalized_sql):
            return self._deny(
                normalized_sql,
                SqlValidationViolationCode.MULTIPLE_STATEMENTS,
                "Only a single SELECT statement is allowed.",
            )

        if self._has_structural_risk(normalized_sql):
            return self._deny(
                normalized_sql,
                SqlValidationViolationCode.STRUCTURAL_RISK,
                "SQL contains a blocked injection pattern.",
            )

        if _DANGEROUS_STATEMENT_PATTERN.search(normalized_sql):
            return self._deny(
                normalized_sql,
                SqlValidationViolationCode.NON_SELECT_STATEMENT,
                "Only SELECT statements are allowed.",
            )

        if not normalized_sql.lower().startswith(_ALLOWED_STATEMENT_PREFIXES):
            return self._deny(
                normalized_sql,
                SqlValidationViolationCode.UNRECOGNIZED_QUERY_OUTPUT,
                "The model's output was not a single read-only query.",
            )

        return SqlValidationResult(normalized_sql=normalized_sql)

    def _deny(
        self,
        normalized_sql: str,
        violation_code: SqlValidationViolationCode,
        message: str,
    ) -> SqlValidationResult:
        return SqlValidationResult(
            normalized_sql=normalized_sql,
            violation_code=violation_code,
            message=message,
        )

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
