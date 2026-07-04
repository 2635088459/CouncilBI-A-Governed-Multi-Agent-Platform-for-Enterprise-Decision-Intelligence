from chatbi.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerState,
    RetryPolicy,
    run_with_retry,
)


def assert_raises(expected_error: type[Exception], action: object) -> Exception:
    try:
        assert callable(action)
        action()
    except expected_error as exc:
        return exc
    raise AssertionError(f"Expected {expected_error.__name__}")


def test_retry_policy_retries_transient_failure_and_applies_backoff() -> None:
    attempts = 0
    sleeps: list[float] = []

    def action() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        return "ok"

    result = run_with_retry(
        action,
        RetryPolicy(max_attempts=2, backoff_seconds=0.5, sleeper=sleeps.append),
    )

    assert result == "ok"
    assert attempts == 2
    assert sleeps == [0.5]


def test_retry_policy_stops_after_bounded_attempts() -> None:
    attempts = 0

    def action() -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("still failing")

    exc = assert_raises(
        RuntimeError,
        lambda: run_with_retry(action, RetryPolicy(max_attempts=3, backoff_seconds=0)),
    )

    assert str(exc) == "still failing"
    assert attempts == 3


def test_circuit_breaker_opens_after_threshold_and_half_opens_after_cooldown() -> None:
    now = 100.0
    breaker = CircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=5.0,
        clock=lambda: now,
    )

    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state is CircuitBreakerState.OPEN
    assert_raises(CircuitBreakerOpenError, breaker.before_call)

    now = 106.0

    assert breaker.state is CircuitBreakerState.HALF_OPEN
    breaker.before_call()


def test_circuit_breaker_success_resets_failure_count() -> None:
    breaker = CircuitBreaker(failure_threshold=2)

    breaker.record_failure()
    breaker.record_success()

    assert breaker.state is CircuitBreakerState.CLOSED
    assert breaker.failure_count == 0
