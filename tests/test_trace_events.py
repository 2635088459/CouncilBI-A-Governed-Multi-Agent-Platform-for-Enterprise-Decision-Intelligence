from datetime import datetime, timedelta, timezone

import pytest

from chatbi.trace_events import (
    InMemoryTraceEventStore,
    TraceEvent,
    TraceEventRecorder,
    TraceEventStatus,
)


STARTED_AT = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
ENDED_AT = STARTED_AT + timedelta(milliseconds=25)


def test_trace_event_matches_spec_required_fields() -> None:
    event = TraceEvent(
        trace_id="trc_trace_contract",
        service="backend-api",
        span_name="request_received",
        status=TraceEventStatus.SUCCEEDED,
        started_at=STARTED_AT,
        ended_at=ENDED_AT,
        latency_ms=25,
    )

    assert event.trace_id == "trc_trace_contract"
    assert event.service == "backend-api"
    assert event.span_name == "request_received"
    assert event.status.value == "succeeded"
    assert event.started_at == STARTED_AT
    assert event.ended_at == ENDED_AT
    assert event.latency_ms == 25


def test_trace_event_allows_started_without_end_time_or_latency() -> None:
    event = TraceEvent(
        trace_id="trc_trace_started",
        service="orchestrator",
        span_name="sql_generated",
        status=TraceEventStatus.STARTED,
        started_at=STARTED_AT,
    )

    assert event.ended_at is None
    assert event.latency_ms is None


def test_trace_event_supports_degraded_status() -> None:
    event = TraceEvent(
        trace_id="trc_trace_degraded",
        service="rag-worker",
        span_name="rag_retrieved",
        status=TraceEventStatus.DEGRADED,
        started_at=STARTED_AT,
        ended_at=ENDED_AT,
        latency_ms=25,
    )

    assert event.status.value == "degraded"


def test_trace_event_validates_trace_id_and_latency() -> None:
    with pytest.raises(ValueError, match="trace_id"):
        TraceEvent(
            trace_id="wrong_prefix",
            service="backend-api",
            span_name="request_received",
            status=TraceEventStatus.SUCCEEDED,
            started_at=STARTED_AT,
        )

    with pytest.raises(ValueError, match="latency_ms"):
        TraceEvent(
            trace_id="trc_bad_latency",
            service="backend-api",
            span_name="request_received",
            status=TraceEventStatus.SUCCEEDED,
            started_at=STARTED_AT,
            ended_at=ENDED_AT,
            latency_ms=-1,
        )


def test_trace_event_store_lists_events_by_trace_id() -> None:
    store = InMemoryTraceEventStore()
    first = TraceEvent(
        trace_id="trc_lookup",
        service="backend-api",
        span_name="request_received",
        status=TraceEventStatus.STARTED,
        started_at=STARTED_AT,
    )
    second = TraceEvent(
        trace_id="trc_lookup",
        service="backend-api",
        span_name="response_sent",
        status=TraceEventStatus.SUCCEEDED,
        started_at=STARTED_AT,
        ended_at=ENDED_AT,
        latency_ms=25,
    )

    store.add(first)
    store.add(second)

    assert store.list_by_trace_id("trc_lookup") == (first, second)
    assert store.list_by_trace_id("trc_missing") == ()
    assert store.list_all() == (first, second)


def test_trace_event_recorder_writes_started_and_completed_events() -> None:
    recorder = TraceEventRecorder(service="backend-api")

    started = recorder.start("trc_recorded", "request_received")
    completed = recorder.complete(
        started,
        status=TraceEventStatus.SUCCEEDED,
        ended_at=started.started_at + timedelta(milliseconds=7),
    )

    events = recorder.store.list_by_trace_id("trc_recorded")

    assert events == (started, completed)
    assert completed.latency_ms == 7


def test_trace_event_recorder_rejects_started_as_completion_status() -> None:
    recorder = TraceEventRecorder(service="backend-api")
    started = recorder.start("trc_bad_completion", "request_received")

    with pytest.raises(ValueError, match="cannot be started"):
        recorder.complete(started, status=TraceEventStatus.STARTED)
