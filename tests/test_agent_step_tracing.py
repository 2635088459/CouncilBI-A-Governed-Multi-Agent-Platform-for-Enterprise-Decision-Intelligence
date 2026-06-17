import pytest

from chatbi.core.contracts import AgentName, AgentStepStatus, new_trace_id
from chatbi.orchestration.tracing import AgentStepTracer, InMemoryAgentTraceLog


def test_tracer_records_start_and_success_events() -> None:
    trace_id = new_trace_id()
    trace_log = InMemoryAgentTraceLog()
    tracer = AgentStepTracer(trace_log)

    result = tracer.run_step(
        trace_id=trace_id,
        agent_name=AgentName.SQL,
        action=lambda: "sql result",
    )

    events = trace_log.list_by_trace_id(trace_id)

    assert result == "sql result"
    assert len(events) == 2
    assert events[0].status is AgentStepStatus.STARTED
    assert events[1].status is AgentStepStatus.SUCCEEDED
    assert events[1].duration_ms is not None
    assert events[1].duration_ms >= 0


def test_tracer_records_start_and_failure_events() -> None:
    trace_id = new_trace_id()
    trace_log = InMemoryAgentTraceLog()
    tracer = AgentStepTracer(trace_log)

    def fail() -> str:
        raise RuntimeError("agent failed")

    with pytest.raises(RuntimeError, match="agent failed"):
        tracer.run_step(
            trace_id=trace_id,
            agent_name=AgentName.RAG,
            action=fail,
        )

    events = trace_log.list_by_trace_id(trace_id)

    assert len(events) == 2
    assert events[0].status is AgentStepStatus.STARTED
    assert events[1].status is AgentStepStatus.FAILED
    assert events[1].duration_ms is not None


def test_tracer_records_skipped_agent_step() -> None:
    trace_id = new_trace_id()
    trace_log = InMemoryAgentTraceLog()
    tracer = AgentStepTracer(trace_log)

    tracer.record_skipped(
        trace_id=trace_id,
        agent_name=AgentName.ANALYTICS,
        summary="SQL step timed out.",
    )

    events = trace_log.list_by_trace_id(trace_id)

    assert len(events) == 1
    assert events[0].status is AgentStepStatus.SKIPPED
    assert events[0].duration_ms == 0
    assert events[0].summary == "SQL step timed out."
