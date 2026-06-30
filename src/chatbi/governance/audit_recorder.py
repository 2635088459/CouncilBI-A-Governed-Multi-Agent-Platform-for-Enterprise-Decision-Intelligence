"""Audit recording orchestration for v2 guardrail decisions."""

from __future__ import annotations

from time import monotonic
from typing import Callable

from chatbi.core.contracts import GuardrailResult, QueryRequest
from chatbi.governance.audit import (
    GuardrailAuditLog,
    GuardrailAuditLogV2,
    GuardrailAuditRecord,
    GuardrailAuditRecordV2,
)
from chatbi.governance.contracts import GuardrailDecisionV2, GuardrailRequestV2


class GuardrailLegacyAuditRecorder:
    """Persist legacy guardrail decisions for local replay and tests."""

    def __init__(self, audit_log: GuardrailAuditLog | None) -> None:
        self._audit_log = audit_log

    def record(
        self,
        original_sql: str,
        request: QueryRequest,
        result: GuardrailResult,
    ) -> GuardrailResult:
        if self._audit_log is None:
            return result

        self._audit_log.save(
            GuardrailAuditRecord(
                trace_id=result.trace_id,
                user_id=request.user_id,
                role=request.role,
                original_sql=original_sql,
                decision=result.decision,
                safe_sql=result.safe_sql,
                error_code=result.error_code,
                message=result.message,
            )
        )
        return result


class GuardrailDecisionAuditRecorder:
    """Persist v2 guardrail decisions with the audit fields required by spec."""

    def __init__(
        self,
        audit_log: GuardrailAuditLogV2 | None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._audit_log = audit_log
        self._clock = clock

    def record(
        self,
        request: GuardrailRequestV2,
        decision: GuardrailDecisionV2,
        started_at: float,
    ) -> None:
        if self._audit_log is None:
            return

        self._audit_log.save_v2(
            GuardrailAuditRecordV2(
                trace_id=request.trace_id,
                user_id=request.user_id,
                role=request.role,
                sql_hash=decision.sql_hash,
                decision=decision.decision,
                rule_hits=tuple(decision.rule_hits),
                latency_ms=self._latency_ms(started_at),
            )
        )

    def _latency_ms(self, started_at: float) -> int:
        return max(0, int((self._clock() - started_at) * 1000))
