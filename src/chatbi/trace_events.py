"""Spec-10 trace event contracts.

`ObservabilitySpan` is the older internal shape used by the app today. This
module is the spec-facing trace event shape: one service span with start/end
time and a computed latency. Keeping it small makes trace persistence and trace
lookup easy to test before swapping in a database-backed store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping

from chatbi.core.contracts import utc_now


def _empty_events() -> dict[str, tuple["TraceEvent", ...]]:
    return {}


def _empty_metadata() -> Mapping[str, object]:
    return {}


class TraceEventStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class TraceEvent:
    trace_id: str
    service: str
    span_name: str
    status: TraceEventStatus
    started_at: datetime
    ended_at: datetime | None = None
    latency_ms: int | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.trace_id.startswith("trc_"):
            raise ValueError("trace_id must start with 'trc_'")
        if not self.service.strip():
            raise ValueError("service is required")
        if not self.span_name.strip():
            raise ValueError("span_name is required")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must be greater than or equal to started_at")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms must be greater than or equal to 0")


@dataclass(slots=True)
class InMemoryTraceEventStore:
    """Tiny trace event store shaped like a future trace_events table."""

    _events_by_trace_id: dict[str, tuple[TraceEvent, ...]] = field(default_factory=_empty_events)

    def add(self, event: TraceEvent) -> None:
        current_events = self._events_by_trace_id.get(event.trace_id, ())
        self._events_by_trace_id[event.trace_id] = (*current_events, event)

    def list_by_trace_id(self, trace_id: str) -> tuple[TraceEvent, ...]:
        return self._events_by_trace_id.get(trace_id, ())

    def list_all(self) -> tuple[TraceEvent, ...]:
        events: list[TraceEvent] = []
        for trace_events in self._events_by_trace_id.values():
            events.extend(trace_events)
        return tuple(events)


class TraceEventRecorder:
    """Small helper for writing started and completed trace events."""

    def __init__(
        self,
        service: str,
        store: InMemoryTraceEventStore | None = None,
    ) -> None:
        if not service.strip():
            raise ValueError("service is required")
        self._service = service
        self._store = store or InMemoryTraceEventStore()

    @property
    def store(self) -> InMemoryTraceEventStore:
        return self._store

    def start(self, trace_id: str, span_name: str) -> TraceEvent:
        event = TraceEvent(
            trace_id=trace_id,
            service=self._service,
            span_name=span_name,
            status=TraceEventStatus.STARTED,
            started_at=utc_now(),
        )
        self._store.add(event)
        return event

    def complete(
        self,
        started_event: TraceEvent,
        status: TraceEventStatus = TraceEventStatus.SUCCEEDED,
        ended_at: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> TraceEvent:
        if status is TraceEventStatus.STARTED:
            raise ValueError("completed trace event status cannot be started")
        active_ended_at = ended_at or utc_now()
        event = TraceEvent(
            trace_id=started_event.trace_id,
            service=started_event.service,
            span_name=started_event.span_name,
            status=status,
            started_at=started_event.started_at,
            ended_at=active_ended_at,
            latency_ms=_latency_ms(started_event.started_at, active_ended_at),
            metadata=metadata or {},
        )
        self._store.add(event)
        return event


def _latency_ms(started_at: datetime, ended_at: datetime) -> int:
    return max(0, int((ended_at - started_at).total_seconds() * 1000))
