"""Rate-limit counter stores shared by API entrypoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class RateLimitCounterStore(Protocol):
    def record_and_check_limited(
        self,
        *,
        key: str,
        limit_per_minute: int,
        now: float,
    ) -> bool:
        """Record one event and return whether the key is already limited."""
        ...


def _empty_events() -> dict[str, list[float]]:
    return {}


@dataclass(slots=True)
class InMemorySlidingWindowRateLimitStore:
    """Shared-store-shaped sliding window counter for local and test runs."""

    _events_by_key: dict[str, list[float]] = field(default_factory=_empty_events)

    def record_and_check_limited(
        self,
        *,
        key: str,
        limit_per_minute: int,
        now: float,
    ) -> bool:
        if limit_per_minute <= 0:
            return False
        recent_events = [
            event_time
            for event_time in self._events_by_key.get(key, [])
            if now - event_time < 60
        ]
        if len(recent_events) >= limit_per_minute:
            self._events_by_key[key] = recent_events
            return True

        recent_events.append(now)
        self._events_by_key[key] = recent_events
        return False
