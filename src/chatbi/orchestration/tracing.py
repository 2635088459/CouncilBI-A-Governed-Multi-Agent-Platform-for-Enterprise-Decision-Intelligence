"""Trace helpers for agent orchestration steps."""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Protocol, TypeVar

from chatbi.core.contracts import (
    AgentName,
    AgentStepStatus,
    AgentTraceEvent,
    ErrorCode,
    utc_now,
)


T = TypeVar("T")


class AgentTraceRepository(Protocol):
    """Persistence boundary for agent trace events.

    The in-memory implementation is used today. A PostgreSQL implementation can
    later keep the same methods and write each event into a durable trace table.
    """

    def add(self, event: AgentTraceEvent) -> None:
        """Persist one start, terminal, or skipped trace event."""
        ...

    def list_by_trace_id(self, trace_id: str) -> tuple[AgentTraceEvent, ...]:
        """Load all events for one request trace."""
        ...

    def list_all(self) -> tuple[AgentTraceEvent, ...]:
        """Load all trace events from this repository."""
        ...


class InMemoryAgentTraceLog:
    """Small trace repository used by tests and local orchestration runs."""

    def __init__(self) -> None:
        self._events: list[AgentTraceEvent] = []

    def add(self, event: AgentTraceEvent) -> None:
        self._events.append(event)

    def list_by_trace_id(self, trace_id: str) -> tuple[AgentTraceEvent, ...]:
        return tuple(event for event in self._events if event.trace_id == trace_id)

    def list_all(self) -> tuple[AgentTraceEvent, ...]:
        return tuple(self._events)


class AgentStepTracer:
    """Record start and terminal events around one agent step."""

    def __init__(self, trace_log: AgentTraceRepository | None = None) -> None:
        self._trace_log = trace_log or InMemoryAgentTraceLog()

    @property
    def trace_log(self) -> AgentTraceRepository:
        return self._trace_log

    def run_step(
        self,
        trace_id: str,
        agent_name: AgentName,
        action: Callable[[], T],
    ) -> T:
        self._trace_log.add(
            AgentTraceEvent(
                trace_id=trace_id,
                agent_name=agent_name,
                status=AgentStepStatus.STARTED,
                occurred_at=utc_now(),
            )
        )
        started_at = perf_counter()

        try:
            result = action()
        except TimeoutError:
            duration_ms = self._duration_ms(started_at)
            self._trace_log.add(
                AgentTraceEvent(
                    trace_id=trace_id,
                    agent_name=agent_name,
                    status=AgentStepStatus.TIMED_OUT,
                    occurred_at=utc_now(),
                    duration_ms=duration_ms,
                    summary=ErrorCode.AGENT_TIMEOUT.value,
                )
            )
            raise
        except Exception:
            duration_ms = self._duration_ms(started_at)
            self._trace_log.add(
                AgentTraceEvent(
                    trace_id=trace_id,
                    agent_name=agent_name,
                    status=AgentStepStatus.FAILED,
                    occurred_at=utc_now(),
                    duration_ms=duration_ms,
                )
            )
            raise

        duration_ms = self._duration_ms(started_at)
        self._trace_log.add(
            AgentTraceEvent(
                trace_id=trace_id,
                agent_name=agent_name,
                status=AgentStepStatus.SUCCEEDED,
                occurred_at=utc_now(),
                duration_ms=duration_ms,
            )
        )
        return result

    def record_skipped(self, trace_id: str, agent_name: AgentName, summary: str) -> None:
        self._trace_log.add(
            AgentTraceEvent(
                trace_id=trace_id,
                agent_name=agent_name,
                status=AgentStepStatus.SKIPPED,
                occurred_at=utc_now(),
                duration_ms=0,
                summary=summary,
            )
        )

    def _duration_ms(self, started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))
