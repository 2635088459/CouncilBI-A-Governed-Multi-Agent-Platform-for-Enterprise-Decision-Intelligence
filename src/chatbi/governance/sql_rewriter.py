"""SQL rewrite helpers used by the guardrail layer."""

from __future__ import annotations

from dataclasses import dataclass
import re


_LIMIT_PATTERN = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SqlRewriteResult:
    """Result of a SQL rewrite pass."""

    sql_text: str
    changed: bool


class RowLimitRewriter:
    """Ensure allowed SELECT SQL cannot return more than the configured rows."""

    def __init__(self, max_rows: int) -> None:
        if max_rows < 1:
            raise ValueError("max_rows must be greater than 0")
        self._max_rows = max_rows

    def rewrite(self, sql_text: str) -> SqlRewriteResult:
        normalized_sql = self._normalize(sql_text)
        limit_match = _LIMIT_PATTERN.search(normalized_sql)
        if limit_match is not None:
            limit_value = int(limit_match.group(0).split()[-1])
            if limit_value <= self._max_rows:
                return SqlRewriteResult(sql_text=normalized_sql, changed=False)

            rewritten_sql = _LIMIT_PATTERN.sub(
                f"LIMIT {self._max_rows}",
                normalized_sql,
                count=1,
            )
            return SqlRewriteResult(sql_text=rewritten_sql, changed=True)

        sql_without_trailing_semicolon = normalized_sql.rstrip(";")
        return SqlRewriteResult(
            sql_text=f"{sql_without_trailing_semicolon} LIMIT {self._max_rows}",
            changed=True,
        )

    def _normalize(self, sql_text: str) -> str:
        return " ".join(sql_text.strip().split())
