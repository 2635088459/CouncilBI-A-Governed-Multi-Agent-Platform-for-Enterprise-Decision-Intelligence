"""Runtime timeout policy for governed SQL execution."""

from __future__ import annotations

from chatbi.core.contracts import ErrorCode, GuardrailDecision, GuardrailResult


class QueryTimeoutPolicy:
    """Deny SQL execution results that exceed the configured timeout."""

    def __init__(self, timeout_ms: int) -> None:
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be greater than 0")
        self._timeout_ms = timeout_ms

    def check(self, elapsed_ms: int, trace_id: str) -> GuardrailResult | None:
        if elapsed_ms <= self._timeout_ms:
            return None

        return GuardrailResult(
            decision=GuardrailDecision.DENY,
            trace_id=trace_id,
            error_code=ErrorCode.SQL_DENY_TIMEOUT,
            message=(
                f"Query exceeded timeout of {self._timeout_ms}ms "
                f"after running for {elapsed_ms}ms."
            ),
        )
