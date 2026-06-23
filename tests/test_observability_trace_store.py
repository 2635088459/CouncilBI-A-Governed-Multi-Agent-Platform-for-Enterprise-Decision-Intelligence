import pytest

from chatbi.observability import (
    InMemoryObservabilityStore,
    ObservabilitySpan,
    TraceRecorder,
    TraceSpanName,
    TraceSpanStatus,
)


def test_observability_store_replays_spans_by_trace_id() -> None:
    store = InMemoryObservabilityStore()
    recorder = TraceRecorder(store)

    recorder.record(
        trace_id="trc_replay",
        span_name=TraceSpanName.REQUEST_RECEIVED,
        attributes={"endpoint": "/api/v1/chat/query"},
    )
    recorder.record(
        trace_id="trc_replay",
        span_name=TraceSpanName.SQL_GENERATED,
        attributes={"sql_text": "SELECT month, revenue FROM revenue_by_month LIMIT 100"},
    )
    recorder.record(
        trace_id="trc_replay",
        span_name=TraceSpanName.RESPONSE_SENT,
        attributes={"status_code": 200},
    )

    replay = store.replay("trc_replay")

    assert replay is not None
    assert replay.completed is True
    assert [span.span_name for span in replay.spans] == [
        TraceSpanName.REQUEST_RECEIVED,
        TraceSpanName.SQL_GENERATED,
        TraceSpanName.RESPONSE_SENT,
    ]
    assert replay.spans[1].attributes["sql_text"].startswith("SELECT ")


def test_observability_store_returns_none_for_unknown_trace_id() -> None:
    store = InMemoryObservabilityStore()

    replay = store.replay("trc_missing")

    assert replay is None


def test_trace_recorder_records_successful_run_span_duration() -> None:
    recorder = TraceRecorder()

    result = recorder.run_span(
        trace_id="trc_run_success",
        span_name=TraceSpanName.SQL_GUARDRAIL_CHECKED,
        action=lambda: "allowed",
        attributes={"decision": "allow"},
    )

    spans = recorder.store.list_spans("trc_run_success")

    assert result == "allowed"
    assert len(spans) == 1
    assert spans[0].status is TraceSpanStatus.SUCCEEDED
    assert spans[0].duration_ms is not None
    assert spans[0].duration_ms >= 0
    assert spans[0].attributes["decision"] == "allow"


def test_trace_recorder_records_failed_run_span_and_reraises() -> None:
    recorder = TraceRecorder()

    def fail() -> str:
        raise RuntimeError("rag retrieval failed")

    with pytest.raises(RuntimeError, match="rag retrieval failed"):
        recorder.run_span(
            trace_id="trc_run_failure",
            span_name=TraceSpanName.RAG_RETRIEVED,
            action=fail,
        )

    spans = recorder.store.list_spans("trc_run_failure")

    assert len(spans) == 1
    assert spans[0].status is TraceSpanStatus.FAILED
    assert spans[0].duration_ms is not None


def test_observability_span_rejects_invalid_trace_id_prefix() -> None:
    with pytest.raises(ValueError, match="trace_id"):
        ObservabilitySpan(
            trace_id="wrong_prefix",
            span_name=TraceSpanName.REQUEST_RECEIVED,
            status=TraceSpanStatus.SUCCEEDED,
        )


def test_standard_trace_span_names_match_spec_order() -> None:
    assert tuple(span.value for span in TraceSpanName) == (
        "request_received",
        "orchestration_planned",
        "sql_generated",
        "sql_guardrail_checked",
        "rag_retrieved",
        "analytics_done",
        "verifier_done",
        "response_sent",
    )
