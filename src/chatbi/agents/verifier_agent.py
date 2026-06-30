"""Verifier agent adapter for lightweight answer verification payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from chatbi.core.contracts import WarningMessage
from chatbi.orchestration.executor import AgentRunResult


@dataclass(frozen=True, slots=True)
class VerifierAgentRunner:
    """Return a minimal verification payload for completed branches."""

    verified: bool
    confidence: float
    reason: str
    sql_text: str | None = None
    warnings: tuple[WarningMessage, ...] = ()
    required_fields: Mapping[str, object] | None = None

    def run(self) -> AgentRunResult:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not self.reason.strip():
            raise ValueError("reason is required")

        findings = self._findings()
        verified = self.verified and not findings
        confidence = self._verified_confidence(verified, findings)
        reason = self._verified_reason(findings)

        return AgentRunResult(
            payload={
                "verified": verified,
                "reason": reason,
                "findings": findings,
            },
            confidence=confidence,
        )

    def _findings(self) -> tuple[str, ...]:
        findings: list[str] = []
        if self.sql_text is not None and not self.sql_text.strip():
            findings.append("SQL text is missing.")
        if self.required_fields is not None:
            missing_fields = tuple(
                field_name
                for field_name, value in self.required_fields.items()
                if value is None
                or value == ""
                or value == ()
                or value == []
                or value == {}
            )
            if missing_fields:
                joined = ", ".join(missing_fields)
                findings.append(f"Required answer field(s) missing: {joined}.")
        if self.warnings:
            warning_codes = ", ".join(warning.code.value for warning in self.warnings)
            findings.append(f"Upstream warning(s) present: {warning_codes}.")
        return tuple(findings)

    def _verified_confidence(self, verified: bool, findings: tuple[str, ...]) -> float:
        if verified:
            return self.confidence
        penalty = 0.2 * max(1, len(findings))
        return max(0.0, round(self.confidence - penalty, 4))

    def _verified_reason(self, findings: tuple[str, ...]) -> str:
        if not findings:
            return self.reason
        return f"{self.reason} Findings: {' '.join(findings)}"
