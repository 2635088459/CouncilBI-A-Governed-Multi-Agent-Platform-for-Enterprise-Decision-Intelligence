"""Rule hit generation for v2 guardrail decisions."""

from __future__ import annotations

from chatbi.core.contracts import ErrorCode
from chatbi.governance.contracts import (
    GuardrailRuleCode,
    MaskingInstruction,
    RuleHit,
)
from chatbi.governance.sql_validator import (
    SqlStatementValidator,
    SqlValidationViolationCode,
)


class GuardrailRuleHitBuilder:
    """Translate guardrail behavior into auditable rule hits."""

    def __init__(self) -> None:
        self._statement_validator = SqlStatementValidator()

    def allow_rule_hits(
        self,
        original_sql: str,
        rewritten_sql: str | None,
        masking_plan: list[MaskingInstruction],
    ) -> list[RuleHit]:
        return [
            *self._row_limit_rule_hits(original_sql, rewritten_sql),
            *self.masking_rule_hits(masking_plan),
        ]

    def deny_rule_hits(
        self,
        sql_text: str,
        error_code: ErrorCode | None,
    ) -> list[RuleHit]:
        if error_code is ErrorCode.SQL_DENY_OBJECT:
            return [
                RuleHit(
                    rule_code=GuardrailRuleCode.UNAUTHORIZED_OBJECT,
                    message="SQL referenced an unauthorized table or field.",
                )
            ]

        validation = self._statement_validator.validate(sql_text)
        if validation.violation_code is SqlValidationViolationCode.MULTIPLE_STATEMENTS:
            return [
                RuleHit(
                    rule_code=GuardrailRuleCode.MULTIPLE_STATEMENTS,
                    message="SQL contained multiple statements.",
                )
            ]

        return [
            RuleHit(
                rule_code=GuardrailRuleCode.WRITE_OPERATION,
                message="SQL contained a blocked statement or unsafe pattern.",
            )
        ]

    def masking_rule_hits(
        self,
        masking_plan: list[MaskingInstruction],
    ) -> list[RuleHit]:
        return [
            RuleHit(
                rule_code=GuardrailRuleCode.MASKING_REQUIRED,
                message=f"Field {instruction.field_name} requires masking.",
                object_name=instruction.field_name,
            )
            for instruction in masking_plan
        ]

    def _row_limit_rule_hits(
        self,
        original_sql: str,
        rewritten_sql: str | None,
    ) -> list[RuleHit]:
        if rewritten_sql is None or self._normalize(original_sql) == rewritten_sql:
            return []
        return [
            RuleHit(
                rule_code=GuardrailRuleCode.ROW_LIMIT_REWRITE,
                message="A row limit was added to the SQL.",
            )
        ]

    def _normalize(self, sql_text: str) -> str:
        return " ".join(sql_text.strip().split())
