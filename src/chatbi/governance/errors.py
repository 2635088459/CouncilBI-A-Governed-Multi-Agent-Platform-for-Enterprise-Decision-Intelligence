"""Structured error payloads for v2 SQL guardrail decisions."""

from __future__ import annotations

from chatbi.core.architecture_contracts import ErrorPayloadV2
from chatbi.core.contracts import ErrorCode


class GuardrailErrorPayloadBuilder:
    """Map internal guardrail errors to the v2 API error contract."""

    def build(
        self,
        error_code: ErrorCode | None,
        message: str | None,
    ) -> ErrorPayloadV2:
        return {
            "code": self._v2_error_code(error_code),
            "message": message or "SQL was denied by guardrail.",
            "retryable": False,
        }

    def _v2_error_code(self, error_code: ErrorCode | None) -> str:
        if error_code is ErrorCode.SQL_DENY_OBJECT:
            return "SQL_DENIED_OBJECT"
        if error_code is ErrorCode.SQL_DENY_TIMEOUT:
            return "SQL_DENIED_TIMEOUT"
        return "SQL_DENIED_WRITE_OPERATION"
