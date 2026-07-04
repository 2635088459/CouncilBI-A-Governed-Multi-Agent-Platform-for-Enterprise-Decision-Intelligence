"""Small resilience primitives shared by external dependency clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic, sleep
from typing import Callable, TypeVar


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a dependency call is blocked by an open circuit."""


class CircuitBreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 2
    backoff_seconds: float = 0.025
    retry_exceptions: tuple[type[BaseException], ...] = (RuntimeError, TimeoutError)
    sleeper: Callable[[float], None] = sleep

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be greater than 0")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must be greater than or equal to 0")
        if not self.retry_exceptions:
            raise ValueError("retry_exceptions are required")


def run_with_retry(action: Callable[[], T], policy: RetryPolicy) -> T:
    last_error: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return action()
        except policy.retry_exceptions as exc:
            last_error = exc
            if attempt < policy.max_attempts and policy.backoff_seconds > 0:
                policy.sleeper(policy.backoff_seconds)
    if last_error is None:
        raise RuntimeError("retry action did not execute")
    raise last_error


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    clock: Callable[[], float] = monotonic
    _state: CircuitBreakerState = field(default=CircuitBreakerState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be greater than 0")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be greater than or equal to 0")

    @property
    def state(self) -> CircuitBreakerState:
        if self._state is CircuitBreakerState.OPEN and self._cooldown_elapsed():
            self._state = CircuitBreakerState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def before_call(self) -> None:
        if self.state is CircuitBreakerState.OPEN:
            raise CircuitBreakerOpenError("Circuit breaker is open.")

    def record_success(self) -> None:
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failure_count += 1
        if (
            self._state is CircuitBreakerState.HALF_OPEN
            or self._failure_count >= self.failure_threshold
        ):
            self._state = CircuitBreakerState.OPEN
            self._opened_at = self.clock()

    def _cooldown_elapsed(self) -> bool:
        return (
            self._opened_at is not None
            and self.clock() - self._opened_at >= self.cooldown_seconds
        )
