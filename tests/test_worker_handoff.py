import pytest

from chatbi.orchestration.worker import (
    AsyncTaskKind,
    AsyncTaskRecord,
    AsyncTaskRequest,
    AsyncTaskStatus,
    InMemoryWorkerHandoffQueue,
    build_mock_worker_queue,
    run_task_status_lookup_benchmark,
)


def test_worker_handoff_creates_task_id_for_async_analytics() -> None:
    queue = InMemoryWorkerHandoffQueue()
    request = AsyncTaskRequest(
        trace_id="tr_analytics_001",
        kind=AsyncTaskKind.ANALYTICS,
        payload={"metric": "revenue", "horizon_days": 30},
    )

    record = queue.enqueue(request)

    assert record.task_id.startswith("task_")
    assert record.trace_id == "tr_analytics_001"
    assert record.kind is AsyncTaskKind.ANALYTICS
    assert record.status is AsyncTaskStatus.QUEUED
    assert queue.get(record.task_id) == record


def test_worker_handoff_creates_task_id_for_indexing() -> None:
    queue = InMemoryWorkerHandoffQueue()
    request = AsyncTaskRequest(
        trace_id="tr_indexing_001",
        kind=AsyncTaskKind.INDEXING,
        payload={"source_id": "doc_001"},
    )

    record = queue.enqueue(request)

    assert record.task_id.startswith("task_")
    assert record.kind is AsyncTaskKind.INDEXING
    assert queue.list_by_trace_id("tr_indexing_001") == (record,)


def test_worker_handoff_marks_task_running_and_succeeded() -> None:
    queue = InMemoryWorkerHandoffQueue()
    record = queue.enqueue(
        AsyncTaskRequest(
            trace_id="tr_indexing_status",
            kind=AsyncTaskKind.INDEXING,
            payload={"source_id": "doc_001"},
        )
    )

    running = queue.mark_running(record.task_id)
    succeeded = queue.mark_succeeded(
        record.task_id,
        result={"document_id": "doc_001", "chunk_count": 3},
    )

    assert running.status is AsyncTaskStatus.RUNNING
    assert succeeded.status is AsyncTaskStatus.SUCCEEDED
    assert succeeded.result == {"document_id": "doc_001", "chunk_count": 3}
    assert succeeded.error_message is None
    assert queue.get(record.task_id) == succeeded


def test_worker_handoff_marks_task_failed_with_error_message() -> None:
    queue = InMemoryWorkerHandoffQueue()
    record = queue.enqueue(
        AsyncTaskRequest(
            trace_id="tr_indexing_failed",
            kind=AsyncTaskKind.INDEXING,
            payload={"source_id": "doc_001"},
        )
    )

    failed = queue.mark_failed(record.task_id, error_message="embedding service unavailable")

    assert failed.status is AsyncTaskStatus.FAILED
    assert failed.error_message == "embedding service unavailable"
    assert failed.result == {}


def test_worker_handoff_rejects_missing_task_status_update() -> None:
    queue = InMemoryWorkerHandoffQueue()

    with pytest.raises(KeyError, match="task_missing"):
        queue.mark_running("task_missing")


def test_async_task_request_requires_trace_id() -> None:
    with pytest.raises(ValueError, match="trace_id"):
        AsyncTaskRequest(
            trace_id="",
            kind=AsyncTaskKind.ANALYTICS,
        )


def test_async_task_record_requires_task_id_prefix() -> None:
    with pytest.raises(ValueError, match="task_id"):
        AsyncTaskRecord(
            task_id="bad_001",
            trace_id="tr_analytics_001",
            kind=AsyncTaskKind.ANALYTICS,
            status=AsyncTaskStatus.QUEUED,
            payload={},
        )


def test_failed_async_task_record_requires_error_message() -> None:
    with pytest.raises(ValueError, match="error_message"):
        AsyncTaskRecord(
            task_id="task_failed",
            trace_id="tr_analytics_001",
            kind=AsyncTaskKind.ANALYTICS,
            status=AsyncTaskStatus.FAILED,
            payload={},
        )


def test_task_status_lookup_benchmark_meets_p95_target_for_ten_thousand_tasks() -> None:
    queue, target_task_id = build_mock_worker_queue(task_count=10_000)

    result = run_task_status_lookup_benchmark(queue, target_task_id, run_count=20)

    assert result.task_count == 10_000
    assert result.run_count == 20
    assert result.returned_task_id == target_task_id
    assert result.max_latency_ms >= result.p95_latency_ms
    assert result.meets_local_p95_target is True


def test_task_status_lookup_benchmark_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="task_count"):
        build_mock_worker_queue(task_count=0)

    queue, target_task_id = build_mock_worker_queue(task_count=1)
    with pytest.raises(ValueError, match="run_count"):
        run_task_status_lookup_benchmark(queue, target_task_id, run_count=0)
    with pytest.raises(ValueError, match="task_id"):
        run_task_status_lookup_benchmark(queue, "wrong_prefix", run_count=1)
    with pytest.raises(ValueError, match="not found"):
        run_task_status_lookup_benchmark(queue, "task_missing", run_count=1)
