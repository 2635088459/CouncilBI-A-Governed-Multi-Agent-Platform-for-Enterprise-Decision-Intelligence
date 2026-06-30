import pytest

from chatbi.core.contracts import ErrorCode, GuardrailDecision
from chatbi.governance import QueryTimeoutPolicy


def test_query_timeout_policy_allows_elapsed_time_within_budget() -> None:
    result = QueryTimeoutPolicy(timeout_ms=1_000).check(
        elapsed_ms=800,
        trace_id="tr_12345678",
    )

    assert result is None


def test_query_timeout_policy_denies_elapsed_time_above_budget() -> None:
    result = QueryTimeoutPolicy(timeout_ms=1_000).check(
        elapsed_ms=1_200,
        trace_id="tr_12345678",
    )

    assert result is not None
    assert result.decision is GuardrailDecision.DENY
    assert result.trace_id == "tr_12345678"
    assert result.error_code is ErrorCode.SQL_DENY_TIMEOUT
    assert result.message == "Query exceeded timeout of 1000ms after running for 1200ms."


def test_query_timeout_policy_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_ms"):
        QueryTimeoutPolicy(timeout_ms=0)
