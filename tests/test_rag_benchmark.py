from chatbi.rag_benchmark import build_mock_rag_service, run_retrieval_benchmark


def test_rag_benchmark_builds_mock_service_with_requested_chunk_count() -> None:
    service = build_mock_rag_service(chunk_count=12)

    assert service.state().indexed_chunk_count == 12


def test_rag_benchmark_runs_retrieval_and_reports_latency_shape() -> None:
    service = build_mock_rag_service(chunk_count=12)

    result = run_retrieval_benchmark(service, run_count=3, limit=5)

    assert result.chunk_count == 12
    assert result.run_count == 3
    assert result.evidence_count == 5
    assert result.p95_latency_ms >= 0.0
    assert result.max_latency_ms >= result.p95_latency_ms
    assert result.meets_local_p95_target is True


def test_rag_benchmark_rejects_invalid_counts() -> None:
    try:
        build_mock_rag_service(chunk_count=0)
    except ValueError as exc:
        assert "chunk_count must be greater than or equal to 1" in str(exc)
    else:
        raise AssertionError("Expected invalid chunk_count to raise ValueError")

    service = build_mock_rag_service(chunk_count=1)
    try:
        run_retrieval_benchmark(service, run_count=0)
    except ValueError as exc:
        assert "run_count must be greater than or equal to 1" in str(exc)
    else:
        raise AssertionError("Expected invalid run_count to raise ValueError")
