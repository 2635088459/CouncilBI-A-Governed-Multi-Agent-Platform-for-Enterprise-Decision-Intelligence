"""SQL agent adapter for the orchestration execution harness."""

from __future__ import annotations

from dataclasses import dataclass

from chatbi.core.contracts import (
    ErrorCode,
    GuardrailDecision,
    GuardrailPort,
    QueryRequest,
)
from chatbi.orchestration.executor import AgentRunResult, AgentStepError


@dataclass(frozen=True, slots=True)
class SqlAgentRunner:
    """Validate a generated SQL candidate before it can be executed."""

    sql_candidate: str
    request: QueryRequest
    trace_id: str
    guardrail: GuardrailPort

    def run(self) -> AgentRunResult:
        guardrail_result = self.guardrail.check(
            sql_text=self.sql_candidate,
            request=self.request,
            trace_id=self.trace_id,
        )
        if guardrail_result.decision is GuardrailDecision.DENY:
            raise AgentStepError(
                error_code=guardrail_result.error_code or ErrorCode.SQL_DENY_STATEMENT,
                message=guardrail_result.message or "SQL was denied by guardrail.",
            )
        return AgentRunResult(
            payload={"safe_sql": guardrail_result.safe_sql or self.sql_candidate},
            confidence=0.9,
        )
