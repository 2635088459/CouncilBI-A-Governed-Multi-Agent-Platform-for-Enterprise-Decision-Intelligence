"""Final answer assembly verification.

Agent verification checks whether upstream branches look trustworthy. This file
checks the final ``QueryAnswer`` just before it is persisted or returned.
"""

from __future__ import annotations

from dataclasses import replace

from chatbi.core.contracts import ErrorCode, QueryAnswer, WarningMessage


class AnswerAssemblyVerifier:
    """Validate the fully assembled answer payload."""

    def verify(self, answer: QueryAnswer) -> QueryAnswer:
        findings = self._findings(answer)
        if not findings:
            return answer

        warning = WarningMessage(
            code=ErrorCode.VERIFICATION_FAILED,
            message=f"Final answer failed assembly verification: {' '.join(findings)}",
        )
        return replace(
            answer,
            warnings=(*answer.warnings, warning),
            confidence=min(answer.confidence, 0.5),
        )

    def _findings(self, answer: QueryAnswer) -> tuple[str, ...]:
        findings: list[str] = []
        if not answer.answer_text.strip():
            findings.append("answer_text is required.")
        if not answer.sql_text.strip():
            findings.append("sql_text is required.")
        if not answer.table_result.columns:
            findings.append("table_result.columns is required.")
        if not answer.trace_id.strip():
            findings.append("trace_id is required.")
        return tuple(findings)
