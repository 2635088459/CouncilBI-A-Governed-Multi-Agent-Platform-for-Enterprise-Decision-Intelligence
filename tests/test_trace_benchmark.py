from chatbi.trace_benchmark import (
    build_mock_trace_event_store,
    run_trace_lookup_benchmark,
)


def test_trace_benchmark_builds_store_with_requested_event_count() -> None:
    store = build_mock_trace_event_store(event_count=12)

    assert len(store.list_all()) == 12
    assert len(store.list_by_trace_id("trc_trace_lookup_target")) == 1


def test_trace_lookup_benchmark_reports_latency_shape_for_ten_thousand_events() -> None:
    store = build_mock_trace_event_store(event_count=10_000)

    result = run_trace_lookup_benchmark(store, run_count=20)

    assert result.event_count == 10_000
    assert result.run_count == 20
    assert result.returned_event_count == 1
    assert result.p95_latency_ms >= 0.0
    assert result.max_latency_ms >= result.p95_latency_ms
    assert result.meets_local_p95_target is True


def test_trace_benchmark_rejects_invalid_inputs() -> None:
    try:
        build_mock_trace_event_store(event_count=0)
    except ValueError as exc:
        assert "event_count must be greater than or equal to 1" in str(exc)
    else:
        raise AssertionError("Expected invalid event_count to raise ValueError")

    try:
        build_mock_trace_event_store(target_trace_id="wrong_prefix")
    except ValueError as exc:
        assert "target_trace_id must start with 'trc_'" in str(exc)
    else:
        raise AssertionError("Expected invalid target_trace_id to raise ValueError")

    store = build_mock_trace_event_store(event_count=1)
    try:
        run_trace_lookup_benchmark(store, run_count=0)
    except ValueError as exc:
        assert "run_count must be greater than or equal to 1" in str(exc)
    else:
        raise AssertionError("Expected invalid run_count to raise ValueError")
