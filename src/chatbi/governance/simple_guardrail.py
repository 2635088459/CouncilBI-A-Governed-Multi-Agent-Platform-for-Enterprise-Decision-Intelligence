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
)


_DANGEROUS_STATEMENT_PATTERN = re.compile(
    r"\b(drop|delete|update|insert|alter|truncate)\b",
    re.IGNORECASE,
)


class SimpleSqlGuardrail:
    """Allow simple SELECT statements and deny dangerous SQL statements."""

    def check(self, sql_text: str, request: QueryRequest, trace_id: str) -> GuardrailResult:
        normalized_sql = self._normalize(sql_text)

        if not normalized_sql:
            return self._deny(trace_id, "SQL text is empty.")

        if self._contains_multiple_statements(normalized_sql):
            return self._deny(trace_id, "Only a single SELECT statement is allowed.")

        if _DANGEROUS_STATEMENT_PATTERN.search(normalized_sql):
            return self._deny(trace_id, "Only SELECT statements are allowed.")

        if not normalized_sql.lower().startswith("select "):
            return self._deny(trace_id, "Only SELECT statements are allowed.")

        return GuardrailResult(
            decision=GuardrailDecision.ALLOW,
            trace_id=trace_id,
            safe_sql=normalized_sql,
        )

    def _deny(self, trace_id: str, message: str) -> GuardrailResult:
        return GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id=trace_id,
            error_code=ErrorCode.SQL_DENY_STATEMENT,
            message=message,
        )

    def _normalize(self, sql_text: str) -> str:
        return " ".join(sql_text.strip().split())

    def _contains_multiple_statements(self, sql_text: str) -> bool:
        stripped_sql = sql_text.rstrip(";")
        return ";" in stripped_sql
