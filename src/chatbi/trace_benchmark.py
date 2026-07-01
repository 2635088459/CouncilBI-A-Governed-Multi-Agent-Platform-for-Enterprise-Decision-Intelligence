"""Local trace lookup benchmark helpers for spec 10."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter

from chatbi.trace_events import InMemoryTraceEventStore, TraceEvent, TraceEventStatus


@dataclass(frozen=True, slots=True)
class TraceLookupBenchmarkResult:
    event_count: int
    run_count: int
    p95_latency_ms: float
    max_latency_ms: float
    returned_event_count: int

    @property
    def meets_local_p95_target(self) -> bool:
        return self.p95_latency_ms <= 250.0


def build_mock_trace_event_store(
    event_count: int = 10_000,
    target_trace_id: str = "trc_trace_lookup_target",
) -> InMemoryTraceEventStore:
    if event_count < 1:
        raise ValueError("event_count must be greater than or equal to 1")
    if not target_trace_id.startswith("trc_"):
        raise ValueError("target_trace_id must start with 'trc_'")

    store = InMemoryTraceEventStore()
    base_time = datetime(2026, 7, 1, tzinfo=timezone.utc)
    target_index = event_count // 2
    for index in range(event_count):
        trace_id = target_trace_id if index == target_index else f"trc_trace_lookup_{index:05d}"
        started_at = base_time + timedelta(milliseconds=index)
        store.add(
            TraceEvent(
                trace_id=trace_id,
                service="backend-api",
                span_name="request_received",
                status=TraceEventStatus.SUCCEEDED,
                started_at=started_at,
                ended_at=started_at,
                latency_ms=0,
            )
        )
    return store


def run_trace_lookup_benchmark(
    store: InMemoryTraceEventStore,
    target_trace_id: str = "trc_trace_lookup_target",
    run_count: int = 20,
) -> TraceLookupBenchmarkResult:
    if run_count < 1:
        raise ValueError("run_count must be greater than or equal to 1")

    latencies_ms: list[float] = []
    returned_event_count = 0
    for _index in range(run_count):
        started_at = perf_counter()
        events = store.list_by_trace_id(target_trace_id)
        latencies_ms.append((perf_counter() - started_at) * 1000)
        returned_event_count = len(events)

    sorted_latencies = tuple(sorted(latencies_ms))
    return TraceLookupBenchmarkResult(
        event_count=len(store.list_all()),
        run_count=run_count,
        p95_latency_ms=_percentile(sorted_latencies, 0.95),
        max_latency_ms=max(sorted_latencies),
        returned_event_count=returned_event_count,
    )


def _percentile(sorted_values: tuple[float, ...], percentile: float) -> float:
    if not sorted_values:
        raise ValueError("sorted_values must not be empty")
    if not 0.0 <= percentile <= 1.0:
        raise ValueError("percentile must be between 0.0 and 1.0")
    index = min(
        len(sorted_values) - 1,
        int(round((len(sorted_values) - 1) * percentile)),
    )
    return sorted_values[index]
